"""Task IR v1 — 사용자 자연어를 보존하면서 FORGE가 실행하기 좋은 구조화 의미 표현으로 정규화.

핵심 불변식(docs/proposal/intent-interpreter-task-ir.md, 마스터 프롬프트 Phase 1):
  - 사용자 원문(original_request)이 최종 authority다. Task IR은 원문을 대체하지 않는다.
  - Interpreter는 사용자가 말하지 않은 요구사항/구현 방법을 발명하지 않는다(프롬프트로 강제).
  - Interpreter는 completion authority가 아니다(완료 판정은 Acceptance Gate가 소유).
  - Interpreter는 file/bash/git tool을 받지 않는다(이 모듈은 도구를 실행하지 않는다).
  - structured output 파싱 실패 시 None을 반환 → 호출측은 기존 routing으로 fallback한다.
  - Interpreter 실패가 전체 run을 실패시키지 않는다(예외를 삼키고 None).

이 모듈은 순수 로직(데이터 모델·파싱·프롬프트 빌더)과, 주입된 adapter로 1회 flash 호출을 하는
interpret()만 담는다. live routing에는 아직 연결하지 않는다(회귀 위험 분리 — A/B 후 통합).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict


@dataclass
class Requirement:
    id: str          # 안정적 ID(R1, R2, …) — gate가 참조할 수 있게.
    text: str
    source: str = "user"   # user | inferred(사용자 원문에서 직접 근거)


@dataclass
class SubtaskHint:
    text: str
    area: str = ""   # frontend | backend | "" (조사/실행 범위 힌트)


@dataclass
class TaskIR:
    version: int
    original_request: str          # 최종 authority — 절대 대체하지 않는다.
    intent: str                    # code_change | question | conversation | investigation | ...
    normalized_goal: str
    requirements: list = field(default_factory=list)     # list[Requirement]
    constraints: list = field(default_factory=list)      # 보존/회귀 방지 등
    non_goals: list = field(default_factory=list)
    clarification_required: bool = False
    clarification_question: str | None = None
    complexity: str = "simple"     # simple | complex
    risk_class: str = "low"        # low | medium | high
    candidate_subtasks: list = field(default_factory=list)  # list[SubtaskHint]

    def to_dict(self) -> dict:
        return asdict(self)


_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
_ALLOWED_INTENT = {"code_change", "question", "conversation", "investigation", "review", "other"}
_ALLOWED_COMPLEXITY = {"simple", "complex"}
_ALLOWED_RISK = {"low", "medium", "high"}


def _clean_list(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def parse_task_ir(data, original_request: str) -> TaskIR | None:
    """모델이 낸 dict(또는 JSON 문자열)를 검증해 TaskIR로 만든다. 실패하면 None(fallback).

    original_request는 호출측이 보유한 사용자 원문을 그대로 쓴다 — 모델이 바꿔도 무시한다
    (원문이 authority). requirement에는 안정적 ID(R1..)를 부여한다.
    """
    if not original_request or not str(original_request).strip():
        return None
    if isinstance(data, str):
        m = _JSON_OBJ.search(data)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(data, dict):
        return None

    intent = str(data.get("intent", "")).strip().lower()
    if intent not in _ALLOWED_INTENT:
        intent = "code_change"   # 애매하면 안전하게 작업으로(triage 기본과 일관)

    reqs: list[Requirement] = []
    for i, r in enumerate(data.get("requirements", []) or [], start=1):
        text = (r.get("text") if isinstance(r, dict) else str(r)) or ""
        text = str(text).strip()
        if not text:
            continue
        src = (r.get("source") if isinstance(r, dict) else "user") or "user"
        reqs.append(Requirement(id=f"R{i}", text=text[:500], source=str(src)))

    subtasks: list[SubtaskHint] = []
    for s in data.get("candidate_subtasks", []) or []:
        text = (s.get("text") if isinstance(s, dict) else str(s)) or ""
        text = str(text).strip()
        if text:
            area = (s.get("area") if isinstance(s, dict) else "") or ""
            subtasks.append(SubtaskHint(text=text[:300], area=str(area)))

    complexity = str(data.get("complexity", "simple")).strip().lower()
    if complexity not in _ALLOWED_COMPLEXITY:
        complexity = "simple"
    risk = str(data.get("risk_class", "low")).strip().lower()
    if risk not in _ALLOWED_RISK:
        risk = "low"

    clar = bool(data.get("clarification_required", False))
    clar_q = data.get("clarification_question")
    clar_q = str(clar_q).strip() if clar_q else None

    return TaskIR(
        version=1,
        original_request=str(original_request),
        intent=intent,
        normalized_goal=str(data.get("normalized_goal", "")).strip()[:800],
        requirements=reqs,
        constraints=_clean_list(data.get("constraints")),
        non_goals=_clean_list(data.get("non_goals")),
        clarification_required=clar,
        clarification_question=clar_q if clar else None,
        complexity=complexity,
        risk_class=risk,
        candidate_subtasks=subtasks,
    )


def build_interpreter_messages(original_request: str) -> list[dict]:
    """저비용 flash 인터프리터용 메시지(순수). 발명 금지·원문 보존을 강하게 지시한다."""
    system = (
        "너는 FORGE의 Intent Interpreter다. 사용자의 요청을 실행하기 좋은 구조화 표현(Task IR)으로 "
        "정규화한다. 계획을 세우거나 구현하지 않는다.\n"
        "규칙:\n"
        "- 사용자가 말한 것만 요구사항으로 만든다. 없는 요구사항·구현 방법·기술 선택을 발명하지 않는다.\n"
        "- 명시적 보존 요구('기존 X 유지', '깨지면 안 됨')는 constraints에 넣는다.\n"
        "- 불명확해 진행이 위험하면 clarification_required=true와 한 문장 질문을 준다.\n"
        "- 오직 아래 JSON 하나만 출력한다(설명·마크다운 금지).\n"
        '{"intent":"code_change|question|conversation|investigation|review|other",'
        '"normalized_goal":"...","requirements":[{"text":"...","source":"user"}],'
        '"constraints":["..."],"non_goals":["..."],"clarification_required":false,'
        '"clarification_question":null,"complexity":"simple|complex","risk_class":"low|medium|high",'
        '"candidate_subtasks":[{"text":"...","area":"frontend|backend|"}]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": str(original_request)[:4000]},
    ]


async def interpret(adapter, original_request: str) -> TaskIR | None:
    """주입된 adapter로 1회 호출해 Task IR을 만든다. 어떤 실패든 None(fallback).

    adapter는 기존 어댑터와 동일하게 async stream_chat(messages) -> async iterator[delta]를 갖는다.
    live routing에는 아직 연결하지 않는다 — 호출측이 None이면 기존 경로를 탄다.
    """
    if not original_request or not str(original_request).strip():
        return None
    try:
        messages = build_interpreter_messages(original_request)
        parts: list[str] = []
        async for delta in adapter.stream_chat(messages):
            if delta.get("content"):
                parts.append(delta["content"])
        return parse_task_ir("".join(parts), original_request)
    except Exception:
        return None   # interpreter 실패가 run을 실패시키지 않는다
