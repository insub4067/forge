import asyncio
import hashlib
import json
import os
import re
import time
import uuid

import httpx
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import settings
from .. import errors as error_log
from .. import eventlog
from ..db import store
from . import approvals
from .. import metrics as metrics_calc
from . import memory_guard
from . import refine
from . import change_guard
from . import verification
from . import task_ir
from . import traceability
from ..security import preflight as security_preflight
# 완료/게이트 판정 정책(순수 함수)은 completion_policy로 분리 — 여기서 re-export해 기존
# 호출부와 A.<name> 인터페이스를 그대로 유지한다.
from .completion_policy import (  # noqa: F401
    needs_gate_recovery,
    _coverage_kind,
    _blocking_reason,
    resolve_completion_verification,
    _clamp_task_status,
    _clamp_gate_status,
)
from ..llm.factory import create_adapter
from ..orchestrator.model_router import ModelRouter
from ..tools.registry import (APPROVAL_REQUIRED, CHAT_TOOLS, TOOL_SCHEMAS,
                              WRITE_OK_PREFIX, execute_tool)
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30
# Developer는 설계+구현+자체검증+수정을 한 루프에서 하므로 step budget을 넉넉히.
# (옛 구조의 planner+coder+reviewer+debugger 여러 호출을 한 컨텍스트로 합친 것)
DEVELOPER_MAX_STEPS = 60
# Planner/Reviewer는 계획·검증 전담이라 step budget이 작아도 충분(비용·지연 억제).
PLANNER_MAX_STEPS = 10
REVIEWER_MAX_STEPS = 12
# Gate 복구는 gate를 쓰는 것 하나만 한다 — 코드를 다시 읽거나 고치지 않으므로 아주 작다.
# 여기가 커지면 "gate 없는 run이 두 번째 Developer 루프를 도는" 비용 사고가 된다.
GATE_RECOVERY_MAX_STEPS = 3
_ROLE_MAX_STEPS = {"developer": DEVELOPER_MAX_STEPS,
                   "planner": PLANNER_MAX_STEPS,
                   "reviewer": REVIEWER_MAX_STEPS,
                   "gate_recovery": GATE_RECOVERY_MAX_STEPS}
# 막혀서 못 풀 때 pro로 승격해 재시도하는 최대 횟수(무한 루프·비용 폭주 방지).
MAX_ESCALATIONS = 2
MAX_REPEATED_CALLS = 3
# working budget 대비 운영 임계치 — config로 분리(hard_context_limit과 구분되는 운영 정책).
# 기본값은 기존과 동일(0.95/0.75)이라 동작 불변. hard block은 working budget 기준이며, working
# budget(logical_budget)은 hard_context_limit보다 훨씬 작아 provider 한도를 넘기 전에 걸린다.
CONTEXT_BLOCK_RATIO = settings.emergency_block_threshold
# 이 비율을 넘으면 오래된 대화를 요약해 모델 컨텍스트를 압축한다(비파괴 — 표시/저장용 원본은 유지).
CONTEXT_COMPACT_RATIO = settings.compaction_threshold
COMPACT_KEEP_RECENT = 8
# 전송본에서 과거 write_file content를 접을 때 보존할 최근 메시지 수(compaction과 별개 정책).
WRITE_ARGS_KEEP_RECENT_MESSAGES = 8
# 부수효과·승인이 없는 읽기 전용 도구 — 한 응답에 여러 개면 병렬 실행 가능
READ_ONLY_TOOLS = {"read_file", "list_dir", "grep", "find_symbol"}
# 파일·프로세스·git에 부수효과를 내는 도구(=승인 대상과 동일). 실행 직후 즉시 history를
# 저장해 crash 후 resume이 같은 부수효과를 재실행하지 않게 한다.
_SIDE_EFFECT_TOOLS = APPROVAL_REQUIRED
# Planner용 도구 스키마(읽기 전용만) — 구현·실행 도구를 주지 않아 계획만 하게 강제한다.
READ_ONLY_TOOL_SCHEMAS = [
    t for t in TOOL_SCHEMAS if t["function"]["name"] in READ_ONLY_TOOLS
]
# Gate 복구용 도구 — gate 등록만. 코드 수정·실행 도구를 주지 않아 "구현을 더 하는" 일탈이
# 구조적으로 불가능하다. 읽기 도구도 주지 않는다(step 3 안에서 탐색 루프를 돌지 않게).
GATE_RECOVERY_TOOL_SCHEMAS = [
    t for t in TOOL_SCHEMAS if t["function"]["name"] == "update_gates"
]

# 종료 사유 → done 이벤트 status 코드 (SSE 프로토콜 비파괴적 확장)
_STATUS_CODES = {
    "cancelled": "cancelled",
    "context_blocked": "context_blocked",
    "budget_exceeded": "budget_exceeded",
    "repeated": "repeated_tool_call",
    "max_steps": "max_steps",
}

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

# 프롬프트·컨텍스트 빌딩·이미지/출력 전처리는 prompts.py로 분리 — 여기서 re-export해
# 기존 호출부와 A.<name> 인터페이스를 그대로 유지한다(completion_policy와 동일 패턴).
from .prompts import (  # noqa: F401
    _has_image,
    _turn_has_image,
    _to_data_uri_item,
    _compress_command_output,
    _prune_tool_result,
    _load_role,
    _load_global_memory,
    _load_room_memory,
    _skill_terms,
    _select_skills,
    _est_tokens,
    _stable_prefix,
    _stable_prefix_hash,
    _system_for,
    _planner_context,
    _reviewer_context,
    build_gate_recovery_context,
    _requirements_block,
    _untraced_requirements,
    _last_assistant_text,
    _plan_to_tasks,
    _format_question,
    _estimate_complexity,
    BASE_PROMPT,
    _COMPLEX_KEYWORDS,
    MAX_ACTIVE_SKILLS,
    SKILL_CHAR_BUDGET,
    _REPO_ROOT,
    AGENTS_DIR,
    GLOBAL_MEMORY_PATH,
    UPLOADS_DIR,
)


class AgentRuntime:
    def __init__(self):
        self.sandbox = DockerSandbox()
        self.router = ModelRouter()
        self._adapters: dict[str, Any] = {}
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self.pending_questions: dict[str, asyncio.Future] = {}
        self._cancel_sessions: set[str] = set()
        # 실행 중인 tool(긴 bash 등)을 즉시 깨우기 위한 취소 이벤트. 플래그는 스텝 경계에서만
        # 폴링돼 실행 중 subprocess를 못 멈췄다 — 이벤트로 tool await를 race해 즉시 중단한다.
        self._cancel_events: dict[str, asyncio.Event] = {}
        # 작업(run) 1회 누적 비용($) — 예산 가드레일. run 시작 시 0으로 리셋.
        self._run_cost: dict[str, float] = {}
        # 세션별 예산 상한($) 재정의(사용자 지정). 없으면 settings.session_budget_usd.
        self._budget: dict[str, float] = {}
        self._injections: dict[str, list[str]] = {}
        self._running_sessions: set[str] = set()
        # 세션별 마지막 이벤트 seq — run마다 0부터 시작하면 폴링 since가 깨지므로
        # 세션 단위로 단조 증가시켜 eventlog.tail(since)의 전제를 보장한다.
        self._last_seq: dict[str, int] = {}
        self._last_context: dict[str, dict] = {}  # 세션별 마지막 context 영역 분해(debug view)
        self._auto_approve_sessions: set[str] = set()
        self._run_ids: dict[str, str] = {}  # session_id → 현재 run 식별자(승인 audit·정리 범위)
        # 세션별 모델 티어: auto(flash+막히면 pro) | pro(항상) | flash(승격 없음)
        self._model_tier: dict[str, str] = {}
        # 세션별 에이전트 모드: auto(복잡도 기반 자동) | multi(경량 3역할) | single(올인원)
        self._agent_mode: dict[str, str] = {}
        # 세션별 컨텍스트 압축 상태: {session_id: {"summary": str, "covered": int}}
        # summary가 all_messages[:covered]를 대체(모델 전송 시에만).
        self._compaction: dict[str, dict] = {}
        # 세션별 Task IR 요구사항(관찰용) — 완료 시 gate와 대조해 traceability를 낸다.
        # ponytail: in-memory, resume 시 유실 허용(완료 시 gate 대조에 쓰고 pop, 영속 불요).
        self._task_ir_reqs: dict[str, list] = {}
        # 세션별 라이브 상태 — 스트림이 끊겨도 언제나 조회 가능해야 한다.
        # {role, last_event, ts(monotonic), waiting_for, pending}
        self._status: dict[str, dict] = {}
        # 대기 중인 승인/질문 future의 메타 — 세션별 취소·복구 조회용.
        # {id: {"session_id", "kind": "approval"|"question", ...detail}}
        self._pending_meta: dict[str, dict] = {}

    # 대기 중인 승인/질문 future의 타임아웃(초). 이 시간 무응답이면 무한 매달림
    # 대신 안전 기본값으로 진행한다(승인→거부, 질문→시간초과 표시).
    PENDING_TIMEOUT = 600

    def _status_update(self, session_id: str, **fields) -> None:
        if not session_id:
            return
        st = self._status.setdefault(session_id, {})
        st.update(fields)
        st["ts"] = time.monotonic()

    @staticmethod
    def _activity_label(event_type: str, data: dict) -> str | None:
        """지금 무엇을 하는지 사람이 읽을 짧은 한 줄(스트림 끊겨도 /status로 노출)."""
        if event_type == "tool_call":
            name = data.get("name", "")
            a = data.get("args") or {}
            hint = a.get("command") or a.get("path") or a.get("query") or ""
            return f"{name} · {str(hint)[:50]}" if hint else f"{name} 실행"
        if event_type == "tool_result":
            return f"{data.get('name', '')} 완료"
        if event_type == "thinking_delta":
            return "추론 중"
        if event_type == "text_delta":
            return "작성 중"
        return None

    def get_status(self, session_id: str) -> dict:
        st = dict(self._status.get(session_id, {}))
        st["running"] = session_id in self._running_sessions
        if "ts" in st:
            st["idle_seconds"] = round(time.monotonic() - st.pop("ts"), 1)
        return st

    def _adapter_for(self, model: str):
        if model not in self._adapters:
            self._adapters[model] = create_adapter(model)
        return self._adapters[model]

    @staticmethod
    def _safe_split(all_messages: list[dict], keep_recent: int) -> int:
        """최근 keep_recent개를 보존하되, 투영본이 orphan tool 메시지로 시작하지 않도록
        안전한 경계를 찾는다. 경계는 user 또는 assistant여야 한다(tool은 금지 — 그 tool_calls
        assistant가 요약에 흡수되면 orphan이 되므로). assistant(tool_calls)는 경계로 허용한다:
        투영본이 그 assistant부터 시작하면 뒤따르는 tool 응답과 쌍으로 유지돼 orphan이 아니다.
        (tool_calls 없는 assistant만 허용하면 user 1개 + 이후 전부 tool 호출인 developer run에서
        경계를 못 찾아 compaction이 영영 안 도는 버그가 있었다.)
        압축할 수 없으면 0을 반환."""
        split = len(all_messages) - keep_recent
        while split > 1:
            role = all_messages[split].get("role")
            if role in ("user", "assistant"):
                return split
            split -= 1
        return 0

    @staticmethod
    def _should_compact(measured_input: int, budget: int) -> bool:
        """압축 임계 판단(순수). measured_input은 provider 실측 입력 컨텍스트."""
        return measured_input > budget * CONTEXT_COMPACT_RATIO

    @staticmethod
    def _effective_budget(override: float | None, default: float) -> float:
        """세션별 예산 override 해석(순수): None=미설정→default, 0=무제한, 양수=cap.
        0.0이 falsy라 'x or default'로 하면 0(무제한)이 default로 새는 버그를 막는다."""
        return override if override is not None else default

    @staticmethod
    def _over_budget(spent: float, cap: float) -> bool:
        """예산 판정(순수) — 상한 cap이 설정(>0)돼 있고 누적 비용이 넘으면 True. cap 0이면 무제한."""
        return bool(cap) and cap > 0 and spent > cap

    @staticmethod
    def _should_block(measured_input: int, budget: int, compacted: bool) -> bool:
        """95% hard block 판단(순수).

        압축이 방금 성공했으면 다음 호출에서 줄어든 컨텍스트가 실측으로 재검증되므로
        차단하지 않는다. 더 이상 압축할 수 없는데도 한도를 넘을 때만 차단한다.
        completion(출력)은 다음 입력에 누적되지 않으므로 압박 계산에서 제외하고,
        provider 실측 prompt_tokens(=방금 보낸 입력 크기)만 기준으로 쓴다."""
        return measured_input > budget * CONTEXT_BLOCK_RATIO and not compacted

    @staticmethod
    def _plain_transcript(messages: list[dict]) -> str:
        lines: list[str] = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ) or "[이미지]"
            text = str(content).strip()
            if m.get("tool_calls"):
                names = ", ".join(tc.get("function", {}).get("name", "") for tc in m["tool_calls"])
                text = (text + f" [도구 호출: {names}]").strip()
            if text:
                lines.append(f"{role}: {text[:800]}")
        return "\n".join(lines)

    async def _compact(self, all_messages: list[dict], session_id: str) -> bool:
        """오래된 대화를 flash로 요약해 self._compaction에 저장한다(비파괴).
        압축이 실제로 일어났으면 True."""
        prev = self._compaction.get(session_id)
        base = prev["covered"] if prev else 0
        split = self._safe_split(all_messages, COMPACT_KEEP_RECENT)
        if split <= base + 2:  # 새로 요약할 구간이 거의 없음
            return False
        old = all_messages[base:split]
        prior = ("이전 요약:\n" + prev["summary"] + "\n\n") if prev else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "다음 에이전트 작업 기록을 요약하라. 목표, 확인한 사실, 변경한 파일, "
                    "남은 작업, 주요 오류를 간결한 한국어 불릿으로. 이후 작업에 필요한 정보를 보존한다."
                ),
            },
            {"role": "user", "content": prior + self._plain_transcript(old)},
        ]
        parts: list[str] = []
        try:
            async for delta in self._adapter_for(self.router.utility_model).stream_chat(messages):
                if delta.get("content"):
                    parts.append(delta["content"])
        except Exception as err:
            error_log.record("compaction_failed", str(err), session_id)
            return False
        summary = "".join(parts).strip()
        if not summary:
            return False
        self._compaction[session_id] = {"summary": summary, "covered": split}
        # 영속화 — 메모리에만 두면 run 종료 시 cleanup_session이 지운다(압축 누적 무효화).
        try:
            await store.set_session_compaction(session_id, summary, split)
        except Exception as err:
            error_log.record("compaction_persist", str(err), session_id)
        return True

    def _project(self, all_messages: list[dict], session_id: str) -> list[dict]:
        """모델에 보낼 메시지 투영: 압축된 구간은 요약본으로 대체(원본은 유지)."""
        comp = self._compaction.get(session_id)
        if not comp:
            return list(all_messages)
        checkpoint = {"role": "user", "content": "[이전 작업 요약 — 컨텍스트 압축됨]\n" + comp["summary"]}
        return [checkpoint, *all_messages[comp["covered"]:]]

    @staticmethod
    def _strip_reasoning(messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            if isinstance(m, dict) and "reasoning_content" in m:
                m = {k: v for k, v in m.items() if k != "reasoning_content"}
            out.append(m)
        return out

    @staticmethod
    def _drop_orphan_tools(messages: list[dict]) -> list[dict]:
        """orphan tool 메시지를 전송 직전에 제거한다.

        tool 메시지는 직전(중간에 다른 tool 허용) assistant의 tool_calls id와 매칭돼야 한다.
        매칭 안 되면 provider가 400("Messages with role 'tool' must be a response to a
        preceding message with 'tool_calls'")을 내고 run이 죽는다. compaction/projection
        경계나 메시지 순서 이상으로 orphan이 섞여도 run이 죽지 않도록 방어한다(원본은 불변)."""
        out: list[dict] = []
        valid_ids: set = set()
        for m in messages:
            role = m.get("role")
            if role == "tool":
                if m.get("tool_call_id") in valid_ids:
                    out.append(m)
                # else: orphan → drop
            else:
                valid_ids = {tc.get("id") for tc in (m.get("tool_calls") or [])} \
                    if role == "assistant" else set()
                out.append(m)
        return out

    @staticmethod
    def _fold_old_write_args(messages: list[dict], keep_recent: int) -> list[dict]:
        """성공한 과거 write_file의 content 인자를 전송본에서 stub으로 접는다.

        write_file(path, content)의 content는 파일 전문이라, 접지 않으면 매 스텝 히스토리에
        실려 재전송된다(실측: tool_call args의 최대 성분). 최근 keep_recent 이내를 뺀 과거
        것만, 그리고 **실제로 성공한** write만 접는다 — 그 assistant 바로 뒤에 오는(protocol상)
        대응 tool result가 성공 마커로 시작할 때만. 승인 거부·오류·취소·결과 없음은 성공한
        것처럼 기록되면 안 되므로 원문을 유지한다. 매칭은 전역 id map이 아니라 이 assistant
        이후 구간에서 찾는다 — 같은 tool_call_id가 재등장해도 과거 실패가 이후 성공 결과로
        잘못 접히지 않게 한다. edit_file(diff 문맥)은 접지 않는다. 원본은 불변(전송본만).

        디스크의 현재 파일은 이후 스텝에서 바뀌었을 수 있어 과거 snapshot이 아니다. stub에
        path·원본 bytes·sha256을 남겨 필요하면 식별·대조할 수 있게 하되, '복구 가능'이라고
        단정하지 않는다."""
        cut = len(messages) - keep_recent
        if cut <= 0:
            return messages

        def _result_after(idx: int, call_id) -> str | None:
            """messages[idx](assistant) 뒤에서 call_id에 대응하는 첫 tool result content.
            다음 assistant(tool_calls 보유)를 만나면 그 구간이 끝난 것으로 보고 중단한다."""
            for m in messages[idx + 1:]:
                if not isinstance(m, dict):
                    continue
                if m.get("role") == "tool" and m.get("tool_call_id") == call_id:
                    return str(m.get("content", ""))
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    break
            return None

        out: list[dict] = []
        for i, m in enumerate(messages):
            tcs = m.get("tool_calls") if isinstance(m, dict) else None
            if i >= cut or not tcs:
                out.append(m)
                continue
            new_tcs = []
            changed = False
            for tc in tcs:
                fn = tc.get("function", {})
                res = _result_after(i, tc.get("id"))
                if fn.get("name") == "write_file" and res is not None \
                        and res.startswith(WRITE_OK_PREFIX):
                    try:
                        a = json.loads(fn.get("arguments") or "{}")
                        body = a.get("content")
                        if isinstance(body, str) and body:
                            raw = body.encode("utf-8")
                            sha = hashlib.sha256(raw).hexdigest()
                            a["content"] = (
                                f"[write_file content 생략 — 성공한 과거 쓰기. "
                                f"원본 {len(raw)}바이트, sha256={sha}. "
                                f"현재 파일은 이후 변경됐을 수 있어 이 시점의 snapshot이 아니다.]"
                            )
                            tc = {**tc, "function": {**fn, "arguments": json.dumps(a, ensure_ascii=False)}}
                            changed = True
                    except (json.JSONDecodeError, TypeError):
                        pass  # malformed arguments는 원문 유지
                new_tcs.append(tc)
            out.append({**m, "tool_calls": new_tcs} if changed else m)
        return out

    @staticmethod
    def _strip_images(messages: list[dict]) -> list[dict]:
        """content 리스트의 image_url 항목을 텍스트 placeholder로 치환한다.
        non-vision 모델은 이미지를 못 받으므로(400), 텍스트만 남긴다.
        원본(all_messages/DB)은 그대로 두고 모델 전송본만 바꾼다."""
        out = []
        for m in messages:
            content = m.get("content") if isinstance(m, dict) else None
            if isinstance(content, list):
                texts = [
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                n_img = sum(
                    1 for c in content
                    if isinstance(c, dict) and c.get("type") == "image_url"
                )
                new = " ".join(t for t in texts if t).strip()
                if n_img:
                    new = (new + f" [이미지 {n_img}장 첨부됨]").strip()
                m = {**m, "content": new or "[이미지]"}
            out.append(m)
        return out

    @staticmethod
    def _classify_error(err: Exception) -> str:
        """LLM 오류를 recover 전략별로 분류: reasoning / transient / terminal."""
        msg = str(err).lower()
        if "reasoning_content" in msg:
            return "reasoning"
        if isinstance(err, (httpx.TimeoutException, httpx.TransportError)):
            return "transient"
        if any(c in msg for c in ("오류 429", "오류 500", "오류 502", "오류 503", "오류 504")):
            return "transient"
        if any(w in msg for w in ("timeout", "connection", "temporarily", "overloaded", "rate limit")):
            return "transient"
        return "terminal"

    async def _stream_with_recovery(self, model, messages, tool_schemas, thinking, effort, session_id, counters=None):
        """LLM 스트림을 호출하되 요청 시점 오류를 유형별로 회복한다.

        - reasoning_content 400: thinking을 꺼서 즉시 재시도. 폴백 상태는 counters에만 담아
          이후 스텝에 전파한다. counters는 _run_role() 호출마다 새로 만들어지므로 폴백의 실제
          범위는 그 role invocation이다 — 같은 _run_role() 안의 후속 step에는 유지되지만,
          새 _run_role() 호출(Developer Pro 승격·verification repair·planner/reviewer 등)과
          Auto Resume에는 새 counters라 상태가 누수되지 않는다. 세션 영구 상태를 두지 않는다.
        - 일시적 오류(429/5xx/timeout/connection): 백오프(1·2·4초) 후 최대 3회 재시도
        - terminal(잘못된 요청·인증 등): 전파
        긴 실행이 네트워크 블립이나 일시적 API 장애로 통째로 죽지 않게 한다.

        reasoning_content 처리: DeepSeek V4 thinking mode는 thinking=True로 호출할 때
        히스토리의 assistant reasoning_content를 그대로 되돌려줘야 한다(누락 시 400).
        따라서 thinking+tools 호출에서는 유지하고, 그 외(비-thinking·tools 없음·폴백)에서만
        벗겨 토큰을 아낀다. 판단은 adapter의 requires_reasoning_replay capability에 위임한다."""
        adapter = self._adapter_for(model)
        # counters에 이전 스텝의 폴백 결과가 실려 있으면(이 role invocation 안에서 이미 400을
        # 겪음) 이번 스텝도 thinking을 끈 채 시작한다 — run_role의 추정과 같은 판단을 공유한다.
        no_think = not self._effective_thinking(thinking, counters)
        transient_attempts = 0
        while True:
            call_thinking = False if no_think else thinking
            call_effort = None if no_think else effort
            # thinking+tools + provider가 replay를 요구하면 reasoning을 유지, 아니면 벗긴다.
            keep_reasoning = self._should_keep_reasoning(adapter, call_thinking, tool_schemas)
            msgs = messages if keep_reasoning else self._strip_reasoning(messages)
            produced = False
            try:
                async for delta in adapter.stream_chat(
                    msgs, tool_schemas, thinking=call_thinking, reasoning_effort=call_effort
                ):
                    produced = True
                    yield delta
                return
            except Exception as err:
                # 델타를 이미 받은 뒤 실패하면 재시도 시 중복 위험 → 전파
                if produced:
                    raise
                kind = self._classify_error(err)
                # reasoning_content 400: thinking을 꺼서 재시도. 정상 tool-loop에서는
                # reasoning을 올바로 round-trip하므로 이 경로는 손상된/재구성된 히스토리
                # (예: reasoning 없는 assistant tool_call)에서만 밟힌다.
                if kind == "reasoning" and not no_think:
                    no_think = True
                    if counters is not None:
                        counters["reasoning_replay_failed"] = True  # role invocation 범위로 전파
                        counters["retries"] = counters.get("retries", 0) + 1
                    error_log.record(
                        "reasoning_replay_fallback",
                        f"reasoning round-trip 실패 → thinking 끄고 재시도(role invocation 한정): {err}",
                        session_id,
                    )
                    continue
                if kind == "transient" and transient_attempts < 3:
                    transient_attempts += 1
                    if counters is not None:
                        counters["retries"] = counters.get("retries", 0) + 1
                    delay = 2 ** (transient_attempts - 1)  # 1, 2, 4초
                    error_log.record("llm_retry", f"{delay}s 후 재시도({transient_attempts}): {err}", session_id)
                    await asyncio.sleep(delay)
                    continue
                raise

    def resolve_approval(self, approval_id: str, decision: str) -> bool:
        fut = self.pending_approvals.pop(approval_id, None)
        if fut and not fut.done():
            fut.set_result(decision)
            return True
        return False

    def answer_question(self, question_id: str, answer: str) -> bool:
        fut = self.pending_questions.pop(question_id, None)
        if fut and not fut.done():
            fut.set_result(answer)
            return True
        return False

    def _cancel_event(self, session_id: str) -> asyncio.Event:
        ev = self._cancel_events.get(session_id)
        if ev is None:
            ev = asyncio.Event()
            self._cancel_events[session_id] = ev
        return ev

    def cancel(self, session_id: str) -> None:
        self._cancel_sessions.add(session_id)
        self._cancel_event(session_id).set()  # 실행 중인 tool await를 즉시 깨운다
        # 승인/질문 future에 매달린 run은 cancel 플래그만으론 안 깨어난다.
        # 대기 future를 resolve해 await를 반환시키면, 다음 스텝에서 cancel을 보고 종료한다.
        for pid, meta in list(self._pending_meta.items()):
            if meta.get("session_id") != session_id:
                continue
            if meta.get("kind") == "approval":
                fut = self.pending_approvals.get(pid)
                if fut and not fut.done():
                    fut.set_result("reject")
            else:
                fut = self.pending_questions.get(pid)
                if fut and not fut.done():
                    fut.set_result("(취소됨)")

    def inject(self, session_id: str, text: str) -> bool:
        """실행 중인 세션에 사용자 메시지를 큐잉한다. 다음 스텝에서 반영된다."""
        if not text.strip():
            return False
        self._injections.setdefault(session_id, []).append(text.strip())
        return True

    def is_running(self, session_id: str) -> bool:
        return session_id in self._running_sessions

    def try_begin(self, session_id: str) -> bool:
        """세션 run을 원자적으로 선점한다(단일 스레드 asyncio라 await 없이 원자적).
        이미 실행 중이면 False — 호출부는 새 run 대신 기존 run에 메시지를 주입한다."""
        if session_id in self._running_sessions:
            return False
        self._running_sessions.add(session_id)
        return True

    def cleanup_session(self, session_id: str) -> None:
        self._running_sessions.discard(session_id)
        self._run_ids.pop(session_id, None)
        self._injections.pop(session_id, None)
        self._cancel_sessions.discard(session_id)
        self._cancel_events.pop(session_id, None)
        self._compaction.pop(session_id, None)
        self._status.pop(session_id, None)
        for pid, meta in list(self._pending_meta.items()):
            if meta.get("session_id") == session_id:
                self._pending_meta.pop(pid, None)

    def set_auto_approve(self, session_id: str, enabled: bool) -> None:
        if enabled:
            self._auto_approve_sessions.add(session_id)
        else:
            self._auto_approve_sessions.discard(session_id)

    def set_model_tier(self, session_id: str, tier: str) -> None:
        self._model_tier[session_id] = tier if tier in ("auto", "pro", "flash") else "auto"

    def set_budget(self, session_id: str, budget_usd: float | None) -> None:
        """이 세션의 작업(run) 비용 상한($) 재정의. None/0이면 기본값·무제한 규칙을 따른다."""
        if budget_usd is None:
            self._budget.pop(session_id, None)
        else:
            self._budget[session_id] = max(0.0, float(budget_usd))

    def set_agent_mode(self, session_id: str, mode: str) -> None:
        """에이전트 모드: auto(복잡도 기반 자동 전환) | multi(Planner→Developer→Reviewer) | single(올인원).
        사용자 선택 UI는 제거됐고 항상 FORGE가 판단한다(auto). 하위호환을 위해 메서드는 유지하되
        저장하지 않는다."""
        return

    def get_agent_mode(self, session_id: str) -> str:
        # 항상 auto — FORGE가 작업 복잡도로 single/multi를 자동 판단한다.
        return "auto"

    async def resolve_pending_approvals(self, session_id: str = "") -> int:
        """해당 세션의 대기 승인을 자동 승인 처리한다(auto_approve 켤 때). PG에서 requested→
        approved 전이를 먼저 성공시킨 것만 메모리 Future를 approve로 해소한다 — PG가 requested로
        남아 실행 직전 consume이 status_requested로 실패하던 불일치를 막는다. DB 오류·상태 경쟁이
        나면 그 승인은 실행하지 않는다(Future를 건드리지 않음). 다른 세션 승인은 절대 건드리지 않는다."""
        count = 0
        for approval_id, fut in list(self.pending_approvals.items()):
            meta = self._pending_meta.get(approval_id, {})
            sid = meta.get("session_id", "")
            if session_id and sid != session_id:
                continue
            if meta.get("kind") != "approval" or fut.done():
                continue
            try:
                ok = await store.decide_approval(approval_id, sid, "approved", "auto_approve")
            except Exception as err:
                error_log.record("auto_approve_decide", str(err), sid)
                continue
            if ok:  # PG 전이 성공한 것만 Future를 approve로 해소
                fut.set_result("approve")
                count += 1
        return count

    @staticmethod
    def _approval_preview(name: str, args: dict) -> str:
        """무엇을 승인하는지 보여줄 안전 축약(원문 전체·파일 내용은 담지 않는다)."""
        try:
            if name in ("write_file", "edit_file"):
                return f"{name}: {args.get('path', '')}"
            if name == "bash":
                return f"bash: {str(args.get('command', ''))[:200]}"
            return f"{name}: {json.dumps(args, ensure_ascii=False)[:200]}"
        except Exception:
            return name

    async def _request_approval(
        self, name: str, args: dict, send: Callable[[str, dict], Awaitable[None]],
        session_id: str = "", run_id: str = "",
    ) -> tuple[str | None, str]:
        """승인을 요청하고 (approval_id, decision)을 반환한다. auto_approve면 (None, "approve").

        durable: 승인 사실을 PG에 requested로 영속화한다(재시작·SSE 재연결 복원, args 변조
        검증 근거). 실행 대기·실시간 UX는 기존 Future/SSE 그대로다. 실제 실행은 호출측이
        consume_approval로 소비할 때만(중복 실행·args 변조·만료 차단)."""
        # 자동 승인 모드면 프롬프트 없이 승인(무인 위임 — PG에 기록하지 않는다, 기존 동작).
        if session_id in self._auto_approve_sessions:
            await send("approval_auto", {"tool": name})
            return None, "approve"
        approval_id = uuid.uuid4().hex
        detail = {"id": approval_id, "tool": name, "args": args}
        # SSE·Future를 먼저 세워 실시간 승인 UX를 막지 않는다. PG 기록(consume 근거)은 그 뒤에
        # 하되, 실패해도 승인 흐름은 SSE/Future로 진행한다(consume 시 not_found면 안전 거부).
        await send("approval_request", detail)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending_approvals[approval_id] = fut
        self._pending_meta[approval_id] = {"session_id": session_id, "kind": "approval", **detail}
        self._status_update(session_id, waiting_for="approval", pending=detail)
        if session_id:
            try:
                await store.create_approval(
                    approval_id, session_id, run_id or self._run_ids.get(session_id, ""), name,
                    approvals.args_hash(args), self._approval_preview(name, args))
            except Exception as err:
                error_log.record("approval_persist", str(err), session_id)
        try:
            try:
                decision = await asyncio.wait_for(fut, self.PENDING_TIMEOUT)
                return approval_id, decision
            except asyncio.TimeoutError:
                # 무응답이면 무한 매달림 대신 안전하게 거부하고 진행한다.
                error_log.record("approval_timeout", f"{name} 승인 {self.PENDING_TIMEOUT}s 무응답 → 거부", session_id)
                if session_id:
                    try:
                        await store.decide_approval(approval_id, session_id, "rejected", "timeout")
                    except Exception:
                        pass
                return approval_id, "reject"
        finally:
            self.pending_approvals.pop(approval_id, None)
            self._pending_meta.pop(approval_id, None)
            self._status_update(session_id, waiting_for=None, pending=None)

    def pending_session(self, approval_id: str) -> str:
        """approval_id를 요청한 세션 id(라우트의 session 격리 검증용). 없으면 ""."""
        meta = self._pending_meta.get(approval_id)
        return meta.get("session_id", "") if meta else ""

    async def _ask_user(
        self, args: dict, send: Callable[[str, dict], Awaitable[None]],
        session_id: str = "",
    ) -> str:
        question_id = uuid.uuid4().hex
        options = list(args.get("options", []) or [])
        # 선택형 질문이면 항상 마지막에 "Forge 판단에 맡기기"를 붙인다 —
        # 사용자가 선택을 모를 때 FORGE(모델)가 스스로 판단해 진행하게 한다.
        if options:
            options = [*options, "Forge 판단에 맡기기"]
        detail = {
            "id": question_id,
            "question": _format_question(args.get("question", "")),
            "options": options,
        }
        await send("question_request", detail)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending_questions[question_id] = fut
        self._pending_meta[question_id] = {"session_id": session_id, "kind": "question", **detail}
        self._status_update(session_id, waiting_for="question", pending=detail)
        try:
            try:
                return await asyncio.wait_for(fut, self.PENDING_TIMEOUT)
            except asyncio.TimeoutError:
                error_log.record("question_timeout", f"질문 {self.PENDING_TIMEOUT}s 무응답 → 진행", session_id)
                return "(응답 시간 초과)"
        finally:
            self.pending_questions.pop(question_id, None)
            self._pending_meta.pop(question_id, None)
            self._status_update(session_id, waiting_for=None, pending=None)

    async def _maybe_interpret(self, full_request: str, send: EventSink,
                               session_id: str = ""):
        """Task IR 인터프리터(Phase 1) — 기본 off. 켜져 있으면 저비용 flash로 원문을 Task IR로
        정규화해 task_ir 이벤트로 발행하고, requirement를 완료 판정(traceability 강등)·gate 작성에 쓴다.
        chat/code 라우팅 자체는 바꾸지 않는다(triage 소유). code route에서만 실행한다.
        실패/None이면 조용히 넘어간다(기존 경로 그대로). off면 어댑터 호출 자체가 없어 비용 0."""
        if not settings.task_ir_enabled or not full_request:
            return None
        try:
            ir = await task_ir.interpret(
                self._adapter_for(self.router.triage_model), full_request)
        except Exception as err:  # noqa: BLE001 — interpreter 실패가 run을 깨뜨리지 않는다
            error_log.record("task_ir", str(err), "")
            return None
        if ir is not None:
            d = ir.to_dict()
            if session_id:
                self._task_ir_reqs[session_id] = d.get("requirements", [])
            await send("task_ir", {"task_ir": d})
        return ir

    async def _triage(self, all_messages: list[dict]) -> tuple[str, int, int]:
        """단순 대화(chat) vs 코드 작업(code) 라우터 — 최저가 flash 1단어 분류.
        (route, prompt_tokens, completion_tokens). 애매하면 code로 보내 안전하게 처리한다."""
        lines: list[str] = []
        for m in all_messages[-4:]:
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content
                                   if isinstance(c, dict) and c.get("type") == "text") or "[이미지]"
            text = str(content).strip()
            if text:
                lines.append(f"{m.get('role', '')}: {text[:400]}")
        messages = [
            {"role": "system", "content": (
                "너는 요청 분류기다. 마지막 사용자 메시지가 파일을 읽거나 고치거나 명령을 "
                "실행해야 하는 코드/작업 요청이면 CODE, 단순 인사·감사·잡담·짧은 질문이면 CHAT 이다. "
                "확신이 없으면 CODE. 'CODE' 또는 'CHAT' 한 단어만 답한다.")},
            {"role": "user", "content": "\n".join(lines)},
        ]
        parts: list[str] = []
        pt = ct = 0
        async for delta in self._adapter_for(self.router.triage_model).stream_chat(messages):
            if delta.get("content"):
                parts.append(delta["content"])
            if delta.get("usage"):
                pt += delta["usage"].get("prompt_tokens", 0)
                ct += delta["usage"].get("completion_tokens", 0)
        route = "chat" if "CHAT" in "".join(parts).upper() else "code"
        return route, pt, ct

    async def _run_role(
        self,
        role: str,
        all_messages: list[dict],
        send: Callable[[str, dict], Awaitable[None]],
        session_id: str,
        ws: str,
        state: dict,
        recent_calls: list[str],
        step_base: int,
        room_memory: str = "",
        retry_count: int = 0,
        tools: list[dict] | None = None,
        skills: str = "",
        complexity: str = "normal",
        escalate: bool = False,
        has_image: bool = False,
        plan: str = "",
        requirements: str = "",
        persist: bool = True,
    ) -> tuple:
        route = self.router.select_model(role, retry_count, complexity, escalate=escalate,
                                         has_image=has_image)
        tool_schemas = tools if tools is not None else TOOL_SCHEMAS
        # 이 role에 실제로 허용된 도구. LLM에 안 준 도구를 이름만 지어내 호출하면(환각) 거부한다.
        # chat 경로는 읽기 전용 도구만 받는데, 모델이 edit_file 등을 호출해 무검증 편집·커밋이
        # 나가던 것을 막는다(실측 — chat run이 파일 9개 편집·커밋).
        allowed_tools = {t["function"]["name"] for t in tool_schemas}
        await send("role_start", {
            "role": role, "model": route["model"], "thinking": route["thinking"],
            "prefix_hash": _stable_prefix_hash(role),
        })
        system_msg = {"role": "system",
                      "content": _system_for(role, room_memory, skills, plan, requirements)}

        total_prompt = 0
        total_completion = 0
        total_hit = 0
        total_miss = 0
        # 작업 단위 성능 계측 — route에 실어 record()로 전달(반환 경로가 여럿이라 route에 누적).
        route["_start"] = time.monotonic()
        route["model_calls"] = 0
        route["tool_calls"] = 0
        route["compactions"] = 0
        counters = {"retries": 0}

        role_max_steps = _ROLE_MAX_STEPS.get(role, MAX_STEPS)
        for step in range(step_base, step_base + role_max_steps):
            if session_id in self._cancel_sessions:
                return "cancelled", total_prompt, total_completion, route

            # 실행 중 사용자가 큐잉한 메시지를 다음 스텝 컨텍스트에 주입
            injected = self._injections.pop(session_id, None) if session_id else None
            if injected:
                for text in injected:
                    user_msg = {"role": "user", "content": "[작업 중 사용자 메시지]\n" + text}
                    all_messages.append(user_msg)
                    await send("user_injected", {"content": text})

            # durable: 스텝마다 진행 history를 저장한다 — 중단(재시작·크래시·스트림 끊김)돼도
            # 완료된 스텝이 유실되지 않고, 재개 시 이 history에서 이어서 계속할 수 있다.
            # (이전엔 run 종료 시 한 번만 저장해 중단되면 그 run 전체가 사라졌다.)
            # persist=False인 역할(planner·reviewer)은 세션 transcript가 아니라 파생된
            # 축소 컨텍스트 위에서 돈다 — 그걸 저장하면 세션 기록을 그 몇 줄로 덮어쓴다.
            if session_id and persist:
                try:
                    await store.save_history(session_id, all_messages)
                except Exception as err:
                    error_log.record("incremental_save", str(err), session_id)

            reasoning: list[str] = []
            content: list[str] = []
            reasoning_buf: list[str] = []
            content_buf: list[str] = []
            tool_acc: dict[int, dict[str, Any]] = {}
            usage: dict[str, int] = {}
            last_emit = 0.0

            # 이 호출에서 reasoning을 전송본에 유지할지 — 사전 압축 추정과 실제 전송이 같은
            # 기준을 쓰도록 여기서 한 번 정한다(DeepSeek V4: thinking+tools면 유지). 같은 role
            # invocation에서 앞선 step이 400 폴백을 겪었으면 effective_thinking이 꺼져 추정본도
            # 전송본과 동일하게 reasoning을 제외한다.
            effective_thinking = self._effective_thinking(route["thinking"], counters)
            keep_reasoning = self._should_keep_reasoning(
                self._adapter_for(route["model"]), effective_thinking, tool_schemas)

            async def _on_compaction(covered):
                route["compactions"] += 1
                await send("compaction", {"covered": covered})

            # 전송 전 사전 압축: 한 스텝에서 도구 결과가 대량으로 쌓이면(예: 병렬 read_file
            # 다수) 실측 후 압축은 이미 예산 초과 호출을 한 번 보내버린다(실측 195K 관측).
            # 실제 전송 형태(reasoning·tool arguments·image 처리 포함)로 추정해 미리 압축한다.
            # 텍스트 영역은 정확도가 높고 이미지는 개수 기반 추정이다(최종 권위는 provider usage).
            projected = await self._precompact(
                session_id, all_messages, system_msg, skills, room_memory,
                keep_reasoning, _on_compaction, has_image=has_image)
            # vision 모델(이미지 작업)이면 원본 이미지를 data URI로 실어 보낸다(/uploads 경로는
            # 모델이 못 읽음). non-vision 모델에는 이미지를 보내지 않는다(모델이 image 미지원 → 400).
            # orphan tool 제거·write_file 접기·image 처리를 실제 전송본에 적용한다(원본 불변).
            send_proj = self._to_send_projection(projected, has_image)
            call_messages = [system_msg, *send_proj]
            # context 영역 분해 계측(debug view/최적화 근거) — 이 step에 '계획된' 요청 기준으로,
            # effective_thinking(폴백 반영)을 써서 compaction 판단과 같은 _estimate_context_areas를
            # 공유한다(reasoning·tool arguments 포함). 같은 step에서 처음 reasoning 400이 나
            # non-thinking으로 재시도되면 그 재시도분은 이 breakdown에 반영되지 않고 다음 step부터
            # 반영된다. 절대값은 추정이며 최종 권위는 provider usage(measured)다.
            if session_id:
                areas = self._estimate_context_areas(
                    system_msg, send_proj, skills, room_memory, keep_reasoning)
                img_stats = self._image_stats(send_proj) if has_image else None
                # 계층형 tree(build_context_tree는 예외를 삼켜 실패해도 실행을 막지 않는다).
                tree = self.build_context_tree(role, send_proj, skills, room_memory, plan, keep_reasoning)
                self._store_context_breakdown(session_id, role, areas, img_stats, tree)
            route["model_calls"] += 1
            # thinking·reasoning은 그대로 넘긴다. reasoning round-trip 유지와 400 폴백(role invocation 한정)은
            # _stream_with_recovery가 adapter capability + counters로 관리한다.
            async for delta in self._stream_with_recovery(
                route["model"],
                call_messages,
                tool_schemas,
                route["thinking"],
                route["reasoning_effort"],
                session_id,
                counters,
            ):
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                    reasoning_buf.append(delta["reasoning_content"])
                if delta.get("content"):
                    content.append(delta["content"])
                    content_buf.append(delta["content"])
                for tc in delta.get("tool_calls", []):
                    idx = tc["index"]
                    acc = tool_acc.setdefault(
                        idx, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        acc["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["arguments"] += fn["arguments"]
                if delta.get("usage"):
                    usage = delta["usage"]

                now = time.monotonic()
                if now - last_emit >= 0.15:
                    if reasoning_buf:
                        await send("thinking_delta", {"content": "".join(reasoning_buf)})
                        reasoning_buf.clear()
                    if content_buf:
                        await send("text_delta", {"content": "".join(content_buf)})
                        content_buf.clear()
                    last_emit = now

            if reasoning_buf:
                await send("thinking_delta", {"content": "".join(reasoning_buf)})
            if content_buf:
                await send("text_delta", {"content": "".join(content_buf)})

            if usage:
                total_prompt += usage.get("prompt_tokens", 0)
                total_completion += usage.get("completion_tokens", 0)
                # provider 실측: cache_hit(캐시에서 제공, 저렴) vs cache_miss(정가).
                # hit+miss == prompt_tokens 이므로 "cached"를 hit+miss로 보면 틀린다.
                hit = usage.get("prompt_cache_hit_tokens", 0)
                miss = usage.get("prompt_cache_miss_tokens", 0)
                total_hit += hit
                total_miss += miss
                route["cache_hit"] = total_hit
                route["cache_miss"] = total_miss
                # 컨텍스트 압박 = provider가 실측한 이번 호출의 입력 컨텍스트(prompt_tokens).
                # 이것이 곧 "방금 모델에 보낸 실제 input"이며 다음 호출도 이 근처에서 시작한다.
                measured_input = usage.get("prompt_tokens", 0)
                await send(
                    "context_usage",
                    {
                        "prompt_tokens": measured_input,
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "cache_hit_tokens": hit,
                        "cache_miss_tokens": miss,
                        "cache_hit_ratio": round(hit / measured_input, 3) if measured_input else 0,
                        "measured": True,
                    },
                )
                if session_id:
                    await store.update_context_usage(session_id, measured_input)
                    # 예산 가드레일 — 이 run의 누적 비용이 상한을 넘으면 안전하게 중단한다.
                    # (무인·자동승인 실행의 runaway 비용 방지. 상한 0이면 무제한.)
                    incr = metrics_calc.run_cost(
                        route["model"], hit, miss, usage.get("completion_tokens", 0)) or 0.0
                    self._run_cost[session_id] = self._run_cost.get(session_id, 0.0) + incr
                    cap = self._effective_budget(
                        self._budget.get(session_id), settings.session_budget_usd)
                    if self._over_budget(self._run_cost[session_id], cap):
                        await send("budget_exceeded", {
                            "spent": round(self._run_cost[session_id], 4), "cap": cap})
                        return "budget_exceeded", total_prompt, total_completion, route
                # 압축 임계 초과 → 오래된 대화를 요약해 컨텍스트를 줄이고 계속(비파괴)
                compacted = False
                if session_id and self._should_compact(measured_input, settings.logical_budget):
                    compacted = await self._compact(all_messages, session_id)
                    if compacted:
                        route["compactions"] += 1
                        await send("compaction", {"covered": self._compaction[session_id]["covered"]})
                # 최후의 안전장치: 압축으로도 못 줄이는데 한도를 넘을 때만 중단.
                # 압축이 방금 성공했다면 다음 호출에서 실측으로 재검증되므로 차단하지 않는다.
                if self._should_block(measured_input, settings.logical_budget, compacted):
                    return "context_blocked", total_prompt, total_completion, route

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": "".join(content)}
            if reasoning:
                assistant_msg["reasoning_content"] = "".join(reasoning)

            tool_calls: list[dict] = []
            for idx in sorted(tool_acc):
                acc = tool_acc[idx]
                tool_calls.append(
                    {
                        "id": acc["id"],
                        "type": "function",
                        "function": {"name": acc["name"], "arguments": acc["arguments"]},
                    }
                )
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
                route["tool_calls"] += len(tool_calls)
            route["retries"] = counters["retries"]

            all_messages.append(assistant_msg)

            if not tool_calls:
                return "done", total_prompt, total_completion, route

            # 읽기 전용 도구가 여러 개면 I/O만 병렬 prefetch(이벤트·순서는 루프에서 그대로 순차 처리).
            prefetched: dict[str, tuple] = {}
            readonly = [t for t in tool_calls if t["function"]["name"] in READ_ONLY_TOOLS]
            if len(readonly) > 1:
                async def _prefetch(t):
                    try:
                        a = json.loads(t["function"]["arguments"] or "{}")
                        return t["id"], await execute_tool(t["function"]["name"], a, ws)
                    except Exception as err:
                        return t["id"], (f"오류: {err}", "")
                results = await asyncio.gather(*[_prefetch(t) for t in readonly])
                prefetched = dict(results)
                await send("parallel_tools", {"count": len(readonly)})

            for tc in tool_calls:
                if session_id in self._cancel_sessions:
                    return "cancelled", total_prompt, total_completion, route

                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    args = {}

                key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                recent_calls.append(key)
                if (
                    len(recent_calls) >= MAX_REPEATED_CALLS
                    and recent_calls[-MAX_REPEATED_CALLS:] == [key] * MAX_REPEATED_CALLS
                ):
                    result = f"동일한 도구 호출이 {MAX_REPEATED_CALLS}회 연속 반복되어 중단합니다."
                    await send("tool_call", {"name": name, "args": args})
                    await send("tool_result", {"name": name, "result": result})
                    all_messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    return "repeated", total_prompt, total_completion, route

                await send("tool_call", {"name": name, "args": args})

                # 이 role에 허용되지 않은 도구는 실행하지 않는다 — 무검증 편집·커밋 차단.
                if name not in allowed_tools:
                    # 자동 분류가 chat으로 판단했는데 모델이 코드 변경(mutation)을 시도한 신호.
                    # 상위(run)가 채팅 run 종료 후 '작업 모드 전환'을 제안하게 표시한다
                    # (repeated_tool_call로 헛돌다 끝나던 것을 self-heal로 바꾼다).
                    if role == "chat" and name in APPROVAL_REQUIRED:
                        route["wanted_mutation"] = True
                    result = (f"[거부] '{name}'은(는) 이 작업에서 쓸 수 없는 도구입니다. "
                              "코드 변경이 필요하면 대화가 아니라 작업 요청으로 다시 보내세요.")
                    await send("tool_result", {"name": name, "result": result})
                    all_messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    continue

                if name == "ask_user":
                    answer = await self._ask_user(args, send, session_id)
                    result = answer if answer else "(응답 없음)"
                    await send("tool_result", {"name": name, "result": result})
                    all_messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    continue

                if name == "update_tasks":
                    tasks = args.get("tasks", [])
                    # invariant: 모델은 todo/working만. testing→done은 프로세스가 소유한다.
                    for _t in tasks:
                        _t["status"] = _clamp_task_status(_t.get("status", "todo"))
                    if session_id:
                        tasks = await store.replace_tasks(session_id, tasks)
                    await send("task_update", {"tasks": tasks})
                    result = f"{len(tasks)}개 태스크를 등록했습니다."
                    await send("tool_result", {"name": name, "result": result})
                    all_messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    continue

                if name == "update_gates":
                    # Acceptance Gate Ledger — 구현 전에 요구사항을 검증 가능한 gate로 분해.
                    # invariant: 모델은 passed/failed를 설정할 수 없다(프로세스가 실제 실행 후 부여).
                    gates = args.get("gates", [])
                    for _g in gates:
                        _g["status"] = _clamp_gate_status(_g.get("status", "pending"))
                    if session_id:
                        gates = await store.replace_gates(session_id, gates)
                    await send("gates_update", {"gates": gates})
                    result = (f"{len(gates)}개 요구사항 게이트를 등록했습니다. "
                              "passed/failed는 프로세스가 검증 실행 후 부여합니다.")
                    await send("tool_result", {"name": name, "result": result})
                    all_messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    continue

                if name in APPROVAL_REQUIRED:
                    approval_id, decision = await self._request_approval(name, args, send, session_id)
                    if decision != "approve":
                        result = "사용자가 실행을 거부했습니다."
                        await send("tool_result", {"name": name, "result": result})
                        all_messages.append(
                            {"role": "tool", "tool_call_id": tc["id"], "content": result}
                        )
                        continue
                    # durable: 실행 직전 승인을 consume한다 — args 변조·만료·중복 실행을 차단하고
                    # approved→consumed로 원자 전이한다. auto_approve는 approval_id 없음 → skip.
                    if approval_id and session_id:
                        ok, why = await store.consume_approval(
                            approval_id, session_id, approvals.args_hash(args))
                        if not ok:
                            result = f"승인을 사용할 수 없습니다({why}). 다시 시도하세요."
                            await send("tool_result", {"name": name, "result": result})
                            all_messages.append(
                                {"role": "tool", "tool_call_id": tc["id"], "content": result}
                            )
                            continue
                    await send("approval_granted", {"name": name})

                # durable 실행 장부 — 이전 run에서 started로만 남은 같은 부작용이 있으면
                # 실제 반영 여부를 알 수 없다. 모르는 것을 자동 재실행하지 않는다(§7).
                # 장부 자체의 오류는 실행을 막지 않는다(fail-open — 장부는 방어지 관문이 아니다).
                _ledger_id = ""
                if session_id and persist and name in _SIDE_EFFECT_TOOLS:
                    _hash = approvals.args_hash(args)
                    _run = self._run_ids.get(session_id, "")
                    try:
                        if await store.has_ambiguous_tool(session_id, name, _hash, _run):
                            result = (
                                f"[재실행 차단] 이 '{name}' 호출은 이전 실행이 시작된 기록만 있고 "
                                "완료 기록이 없습니다(서버 중단 추정). 실제로 반영됐는지 알 수 없어 "
                                "같은 인자로 자동 재실행하지 않습니다. 현재 상태를 먼저 확인한 뒤"
                                "(read_file·git diff·git log) 필요한 만큼만 진행하세요.")
                            await send("tool_result", {"name": name, "result": result})
                            all_messages.append(
                                {"role": "tool", "tool_call_id": tc["id"], "content": result}
                            )
                            # 경고는 1회 — 알린 뒤 행을 닫는다(영구 차단이 아니다).
                            await store.resolve_ambiguous_tool(session_id, name, _hash)
                            continue
                        _ledger_id = await store.ledger_start(session_id, _run, name, _hash)
                    except Exception as err:
                        error_log.record("tool_ledger", str(err), session_id)

                diff = ""
                try:
                    if tc["id"] in prefetched:
                        result, diff = prefetched[tc["id"]]  # 병렬 prefetch된 읽기 결과
                    else:
                        _r = await self._exec_tool_cancellable(name, args, ws, session_id)
                        if _r is None:  # 실행 중 사용자가 취소 — subprocess까지 종료됨
                            return "cancelled", total_prompt, total_completion, route
                        result, diff = _r
                    if name in ("write_file", "edit_file") and not result.startswith("오류"):
                        state["files_changed"].append(str(args.get("path")))
                except Exception as err:
                    result = f"오류: {err}"
                    state["errors"].append(f"{name}: {err}")

                await send("state_update", state)
                await send(
                    "tool_result",
                    {"name": name, "result": result[:20_000], "diff": diff[:10_000]},
                )

                # bash는 명령 종류별 압축을 먼저 시도(성공 명확 시 강하게, 실패는 원본 보존).
                _ca = _compress_command_output(args.get("command", ""), result) if name == "bash" else None
                _content = _ca if _ca is not None else _prune_tool_result(result)
                # RTK식 gain — 도구 결과 압축 전/후 추정 토큰 누적(절감량 측정).
                route["tool_raw"] = route.get("tool_raw", 0) + _est_tokens(result)
                route["tool_visible"] = route.get("tool_visible", 0) + _est_tokens(_content)
                all_messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": _content}
                )
                # durable: side-effect 도구는 실행 직후 즉시 history를 저장해 재실행 창을 없앤다.
                # save가 스텝 시작에만 있으면, side effect 완료 후 다음 스텝 save 전 crash 시
                # 그 tool_call이 저장되지 않아 resume이 같은 부작용을 다시 실행한다(write/bash/git
                # 중복). 여기서 즉시 저장하면 crash 후 resume이 이미 실행된 결과를 history로 보고
                # 재실행하지 않는다. 읽기 전용 도구는 무해하므로 대상이 아니다.
                if session_id and persist and name in _SIDE_EFFECT_TOOLS:
                    try:
                        await store.save_history(session_id, all_messages)
                        # 저장이 끝난 뒤에만 장부를 닫는다 — 저장에 실패했는데 닫으면
                        # history에 없는 부작용이 '기록된 실행'으로 둔갑한다.
                        if _ledger_id:
                            await store.ledger_complete(_ledger_id)
                    except Exception as err:
                        error_log.record("side_effect_save", str(err), session_id)

        return "max_steps", total_prompt, total_completion, route

    async def _exec_tool_cancellable(self, name, args, ws, session_id):
        """execute_tool을 실행하되, 실행 중 취소되면 하위 subprocess까지 죽이고 None을 반환한다.
        긴 bash가 취소 플래그를 스텝 경계에서만 봐서 못 멈추던 구멍을 메운다.
        정상 완료 시 (result, diff), 취소 시 None."""
        if not session_id:
            return await execute_tool(name, args, ws)
        tool_task = asyncio.ensure_future(execute_tool(name, args, ws))
        cancel_task = asyncio.ensure_future(self._cancel_event(session_id).wait())
        try:
            await asyncio.wait({tool_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            cancel_task.cancel()
        if tool_task.done() and not self._cancel_event(session_id).is_set():
            return tool_task.result()
        # 취소됨 — 실행 중 tool을 중단하면 executor가 CancelledError에서 subprocess를 죽인다.
        tool_task.cancel()
        try:
            await tool_task
        except (asyncio.CancelledError, Exception):
            pass
        return None

    async def _finalize_tasks(self, session_id: str, send: EventSink) -> None:
        """성공 완료 시 남은 task를 done으로 마감한다 — 모델이 update_tasks로 상태를
        안 올려 칸반이 todo에 멈추는 문제를 하네스가 backstop한다."""
        if not session_id:
            return
        try:
            tasks = await store.list_tasks(session_id)
            if not tasks:
                return
            changed = False
            for t in tasks:
                if t.get("status") != "done":
                    t["status"] = "done"
                    changed = True
            if changed:
                tasks = await store.replace_tasks(session_id, tasks)
                await send("task_update", {"tasks": tasks})
        except Exception as err:
            error_log.record("finalize_tasks", str(err), session_id)

    async def _fail_pending_tasks(self, session_id: str, send: EventSink) -> None:
        """비완료 종료(verification_failed/cancelled/budget/max_steps 등) 시 아직 done이 아닌
        task를 blocked로 강등한다. testing은 '검증 중'을 뜻하는데 run이 실패로 멈추면 아무도
        검증하지 않으므로, testing/working에 그대로 두면 칸반이 '진행 중'처럼 거짓 표시된다."""
        if not session_id:
            return
        try:
            tasks = await store.list_tasks(session_id)
            if not tasks:
                return
            changed = False
            for t in tasks:
                if t.get("status") in ("testing", "working"):
                    t["status"] = "blocked"
                    changed = True
            if changed:
                tasks = await store.replace_tasks(session_id, tasks)
                await send("task_update", {"tasks": tasks})
        except Exception as err:
            error_log.record("fail_pending_tasks", str(err), session_id)

    async def _check_change_risks(self, ws: str, send: EventSink, files_changed: list) -> None:
        """이번 변경의 위험 신호를 감지해 경고로 표면화한다(비차단, verdict 미변경).

        gate가 못 잡는 두 false_completion 벡터를 가시화한다:
          - 테스트 약화: `git diff --numstat HEAD`로 테스트 파일 삭제/라인 순감소 감지.
          - 민감 파일 변경: 시크릿·키·의존성 lock·CI·git 훅 등 고위험 파일 변경 감지.
        정당한 리팩터를 자동 차단하지 않으려 사실만 드러낸다. 감지 실패는 run을 깨뜨리지 않는다."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", ws, "diff", "--numstat", "HEAD",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            weak = change_guard.detect_test_weakening(out.decode("utf-8", "replace"))
            # 삭제/라인 순감소(numstat)로 안 잡히는 skip/xfail/only 우회를 diff 내용으로 추가 감지.
            try:
                dproc = await asyncio.create_subprocess_exec(
                    "git", "-C", ws, "diff", "--unified=0", "HEAD",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                dout, _ = await asyncio.wait_for(dproc.communicate(), timeout=10)
                weak += change_guard.detect_skipped_tests(dout.decode("utf-8", "replace"))
            except Exception:
                pass
            if weak:
                await send("test_weakening", {"warnings": weak})
        except Exception as err:  # noqa: BLE001 — 감지 실패가 run을 깨뜨리지 않는다
            error_log.record("test_weakening_check", str(err), "")
        try:
            sensitive = change_guard.detect_sensitive_changes(files_changed)
            if sensitive:
                await send("sensitive_change", {"warnings": sensitive})
        except Exception as err:  # noqa: BLE001
            error_log.record("sensitive_change_check", str(err), "")

    async def _mark_testing(self, session_id: str, send: EventSink) -> None:
        """검증(test) 단계 진입 시 남은 task를 testing으로 — 프로세스가 칸반 stage를 소유한다
        (todo→working은 모델이, testing→done은 프로세스가). 칸반이 진행 상태를 정직히 반영."""
        if not session_id:
            return
        try:
            tasks = await store.list_tasks(session_id)
            changed = False
            for t in tasks:
                if t.get("status") not in ("done", "testing"):
                    t["status"] = "testing"
                    changed = True
            if changed:
                tasks = await store.replace_tasks(session_id, tasks)
                await send("task_update", {"tasks": tasks})
        except Exception as err:
            error_log.record("mark_verifying", str(err), session_id)

    async def _autocommit(self, ws: str, goal: str, send: EventSink,
                          paths: list[str] | None = None, push: bool = True) -> tuple[bool, bool]:
        """성공 완료 시 git 워크스페이스면 자동 commit(+선택적 push) — 커밋 누락 방지.

        (committed, pushed)를 돌려준다 — 완료 리포트가 추측 대신 실제 결과를 말하게 한다.

        push=False면 로컬 commit만 하고 origin push는 하지 않는다 — 미검증(completed_unverified)
        결과가 자동으로 원격에 나가지 않게 하는 안전장치(검증된 것만 배포 경로로).

        **에이전트가 실제로 바꾼 경로만** stage·commit한다. `git add -A`는 사람이 편집 중이던
        미커밋 변경까지 에이전트 커밋으로 밀어 올려 push해 버린다(실제 사고 2건).
        best-effort: 실패해도 run을 막지 않는다. AUTO_COMMIT=0으로 끈다.
        ponytail: write_file/edit_file로 바꾼 파일만 센다. bash로 고친 파일은 커밋되지 않는다
        (그 편은 놓치는 쪽이 남의 변경을 커밋하는 쪽보다 안전하다).
        """
        if not settings.auto_commit or not ws:
            return False, False
        rel: list[str] = []
        for raw in paths or []:
            q = str(raw or "").strip()
            if not q:
                continue
            if os.path.isabs(q):
                try:
                    q = os.path.relpath(q, ws)
                except ValueError:
                    continue
            if q.startswith(".."):  # 워크스페이스 밖은 커밋 대상 아님
                continue
            if q not in rel:
                rel.append(q)
        if not rel:
            return False, False

        async def _g(*args, timeout=90):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "-C", ws, *args,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode, out.decode(errors="replace")
            except Exception:
                return 1, ""

        try:
            rc, out = await _g("rev-parse", "--is-inside-work-tree", timeout=10)
            if rc != 0 or "true" not in out:
                return False, False  # git 저장소가 아님
            rc, out = await _g("status", "--porcelain", "--", *rel, timeout=15)
            if rc != 0 or not out.strip():
                return False, False  # 에이전트가 바꾼 파일에 실제 변경 없음
            msg = f"chore: FORGE 자동 커밋 — {(goal or '작업').strip()[:60]}"
            await _g("add", "--", *rel, timeout=30)
            # 경로를 명시해 커밋 — 사람이 stage해 둔 다른 변경이 섞이지 않는다.
            rc, _ = await _g("commit", "-m", msg, "--", *rel, timeout=30)
            committed = rc == 0
            pushed = False
            if committed and push:
                rc, _ = await _g("push", timeout=90)
                pushed = rc == 0
            await send("autocommit", {"committed": committed, "pushed": pushed, "message": msg,
                                      "push_skipped": committed and not push})
            return committed, pushed
        except Exception as err:
            error_log.record("autocommit", str(err), "")
            return False, False

    async def _reflect(self, session_id: str, ws: str, status: str, send: EventSink) -> None:
        """run이 끝나면 실행 근거를 모아 개선 후보(RefinementCandidate)를 만든다.

        여기서 **아무것도 적용하지 않는다** — 후보를 저장하고 사용자에게 보여줄 뿐이다.
        근거는 eventlog의 결정적 사실(검증 실패 리포트)뿐이고, 서로 다른 run에서
        같은 실패가 반복될 때만 후보가 된다(1회 관측으로 학습 금지).
        학습은 실행 신뢰성보다 우선순위가 낮다 — 여기서 나는 예외가 run을 깨지 않는다.
        """
        if not session_id:
            return
        try:
            events = eventlog.tail(session_id, limit=600)
            failures = refine.scan_failures(events)
            # 이번 run은 아직 done을 보내기 전이다 → 지금까지의 done 수가 이번 run 번호.
            current = f"{session_id}#{sum(1 for e in events if e.get('type') == 'done')}"
            mine = [f for f in failures if f["run"] == current]
            if not mine:
                return
            runs = await store.session_agent_runs(session_id)
            cost, _priced, _total = metrics_calc.sum_cost(runs)
            evidence = {
                "final_status": status,
                # 검증이 한 번 실패한 뒤 완료됐다면 수리(repair)가 실제로 동작한 것.
                "repair_used": status in ("completed", "completed_unverified"),
                "succeeded": status == "completed",
                "session_cost_usd": cost,
                "verify_failures_this_run": len(mine),
            }
            target = refine.target_for(mine[-1]["report"])
            before = ""
            skill_path = Path(ws) / ".forge" / "skills" / f"{target}.md"
            if skill_path.is_file():
                before = skill_path.read_text(encoding="utf-8")
            candidate = refine.propose(current, failures, before=before, evidence=evidence)
            if not candidate:
                return
            saved = await store.save_refinement(session_id, candidate)
            if not saved:  # 같은 실패 패턴의 후보가 이미 있다(중복 제안 금지).
                return
            await send("refinement_candidate", {
                "id": saved["id"],
                "type": saved["type"],
                "scope": saved["scope"],
                "target": saved["target"],
                "failure_pattern": saved["failure_pattern"],
                "expected_effect": saved["expected_effect"],
                "evidence_runs": saved["evidence_runs"],
                "evidence": saved["evidence"],
            })
        except Exception as err:  # 학습 실패가 run 결과를 바꾸면 안 된다.
            error_log.record("reflect", str(err))

    # 검증(test/build)이 만든 잔존 파일이 이후 검증을 오염시키는 것을 막는다(멱등화).
    # 예: state.json에 상태를 영속하는 stateful 테스트는 1회차 실행이 파일을 남기고,
    # 2회차(integration)가 그 잔존 상태로 깨진다 — 코드는 정답인데 이중검증이 과차단.
    # generic·integration이 모두 _verify를 타므로 여기 한 곳에서 막으면 전 경로가 멱등.
    _VERIFY_SNAPSHOT_SKIP = {".git", ".venv", "node_modules",
                             "__pycache__", ".pytest_cache", ".mypy_cache"}

    @classmethod
    def _verify_snapshot(cls, ws: str) -> set:
        """검증 실행 직전 워크스페이스 파일 집합 스냅샷. 무겁고/건드리면 안 되는
        디렉터리(.git/.venv/node_modules 등)는 제외 — 정리 대상도 아니다."""
        seen = set()
        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs if d not in cls._VERIFY_SNAPSHOT_SKIP]
            for f in files:
                seen.add(os.path.join(root, f))
        return seen

    @classmethod
    def _verify_cleanup(cls, ws: str, before: set) -> None:
        """검증이 **새로 만든** 파일만 제거해 워크스페이스를 검증 전 상태로 되돌린다.
        스냅샷에 이미 있던 파일(구현 산출물)은 건드리지 않는다 — 판정에는 관여 안 함
        (state/report 확정 후 실행). 실제 실패 탐지도 약화되지 않는다(파일만 청소)."""
        for path in cls._verify_snapshot(ws) - before:
            try:
                os.remove(path)
            except OSError:  # 이미 없거나 권한 문제면 무시 — 청소 실패가 결과를 바꾸면 안 됨
                pass

    async def _verify(self, ws: str, send: EventSink,
                      stage: str = "generic") -> tuple[str, str]:
        """3상태 검증 — 프로세스가 test/build를 직접 실행. 반환 (state, report),
        state ∈ {"passed","failed","unavailable"}.
        - passed: 실제 검증이 돌아 통과.
        - failed: 실제 검증이 돌아 실패(assertion/build error) → 완료 아님, 커밋 금지.
        - unavailable: 검증 대상 없음 or 실행 불가(미설치/수집0/설정오류/timeout).
          '검증 못 함'을 '검증 성공'으로 기록하지 않으려 별도 상태로 둔다.
        정책: 하나라도 failed→failed. 아니고 하나라도 passed→passed. 전부 unavailable→unavailable.
        흔한 구조만 지원: root/frontend package.json build, root/backend pytest(과설계 금지).
        """
        import os
        import shutil
        import glob
        if not ws or not os.path.isdir(ws):
            return "unavailable", "검증 대상 없음(워크스페이스 없음)"

        async def _sh(args, cwd, timeout=240):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=cwd,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode, out.decode(errors="replace")
            except Exception as err:
                return -1, f"실행 오류: {err}"

        checks: list[tuple[str, list[str], str, str]] = []  # (label, args, cwd, kind)
        npm = shutil.which("npm")
        for sub in ("", "frontend"):
            d = os.path.join(ws, sub)
            pj = os.path.join(d, "package.json")
            # node_modules 없으면 빌드가 환경 문제로 깨진다 — 거짓 failed 방지 위해 스킵(unavailable).
            if npm and os.path.isfile(pj) and os.path.isdir(os.path.join(d, "node_modules")):
                try:
                    scripts = json.loads(open(pj, encoding="utf-8").read()).get("scripts", {})
                except Exception:
                    scripts = {}
                if "build" in scripts:
                    checks.append((f"npm run build{f' ({sub})' if sub else ''}",
                                   [npm, "run", "build"], d, "build"))
        for sub in ("", "backend"):
            d = os.path.join(ws, sub)
            if os.path.isdir(d) and glob.glob(os.path.join(d, "test_*.py")):
                venv_py = os.path.join(d, ".venv", "bin", "python")
                interp = venv_py if os.path.isfile(venv_py) else (shutil.which("python3") or shutil.which("python"))
                # pytest 설치된 경우에만 검증으로 취급(미설치=unavailable, 거짓 failed 방지).
                if interp and (await _sh([interp, "-c", "import pytest"], d, timeout=20))[0] == 0:
                    checks.append((f"pytest{f' ({sub})' if sub else ''}",
                                   [interp, "-m", "pytest", "-q"], d, "pytest"))

        # ruff — 설정 파일(ruff.toml/.ruff.toml/pyproject [tool.ruff])이 있는(=ruff를 채택한)
        # 저장소에서만 린트 게이트. 미설정·미설치=검증대상 아님(거짓 failed 방지). 코드 이동으로
        # 생기는 고아 import(F401) 등 CI가 잡는 결함을 '완료' 전에 잡는다. --fix 안 함(멱등 유지).
        for sub in ("", "backend"):
            d = os.path.join(ws, sub)
            if not os.path.isdir(d):
                continue
            has_cfg = os.path.isfile(os.path.join(d, "ruff.toml")) or \
                os.path.isfile(os.path.join(d, ".ruff.toml"))
            if not has_cfg:
                try:
                    has_cfg = "[tool.ruff" in open(
                        os.path.join(d, "pyproject.toml"), encoding="utf-8").read()
                except OSError:
                    has_cfg = False
            venv_ruff = os.path.join(d, ".venv", "bin", "ruff")
            ruff_bin = venv_ruff if os.path.isfile(venv_ruff) else shutil.which("ruff")
            if has_cfg and ruff_bin:
                checks.append((f"ruff{f' ({sub})' if sub else ''}",
                               [ruff_bin, "check", "."], d, "ruff"))

        if not checks:
            return "unavailable", "검증 대상 없음(test/build 미검출 또는 실행 불가)"
        # 검증 실행이 만든 새 파일을 이 호출 종료 시 청소한다(멱등화) — generic·integration
        # 이중검증이 같은 초기 상태에서 돌게 해, stateful 테스트의 잔존 상태 오염을 막는다.
        before = self._verify_snapshot(ws)
        try:
            await send("verify_start", {"checks": [c[0] for c in checks], "stage": stage})
            any_passed = False
            unavailable_reasons: list[str] = []
            for label, args, cwd, kind in checks:
                rc, out = await _sh(args, cwd)
                if kind == "pytest":
                    if rc == 0:
                        any_passed = True
                    elif rc == 1:
                        return "failed", f"[{label}] 테스트 실패 (exit 1):\n{out[-1500:]}"
                    else:
                        # 2=중단, 3=내부 오류, 4=설정/사용법 오류, 5=테스트 수집 0,
                        # -1=timeout/실행 불가 — 조용히 건너뛰면 다른 passed check에 묻혀
                        # 전체가 PASS로 오판될 수 있다. unavailable로 남겨 승격을 막는다.
                        unavailable_reasons.append(f"[{label}] exit {rc} (실행/설정 오류 또는 테스트 없음)")
                elif kind == "ruff":
                    if rc == 0:
                        any_passed = True
                    elif rc == 1:  # 린트 위반(고아 import 등) → CI가 거부하는 결함. 완료 아님.
                        return "failed", f"[{label}] 린트 실패 (미사용 import 등, exit 1):\n{out[-1500:]}"
                    else:  # 2=설정/사용 오류, -1=실행 불가 → unavailable(거짓 failed 방지)
                        unavailable_reasons.append(f"[{label}] exit {rc} (ruff 실행/설정 오류)")
                else:  # build: 0=통과, 양수=실패(빌드/타입 깨짐), -1(실행 불가)=unavailable
                    if rc == 0:
                        any_passed = True
                    elif isinstance(rc, int) and rc > 0:
                        return "failed", f"[{label}] 빌드 실패 (exit {rc}):\n{out[-1500:]}"
                    else:
                        unavailable_reasons.append(f"[{label}] 실행 불가 (exit {rc})")
            if unavailable_reasons:
                # 실행/설정 오류가 하나라도 있으면 '검증 통과'로 기록하지 않는다 — PASS 오판 금지.
                return "unavailable", "검증 일부 실행 불가: " + "; ".join(unavailable_reasons)
            # self-repo 런타임 스모크 — build는 통과하지만 런타임에 앱이 깨지는 것을 잡는다
            # (undefined ref로 크래시·핵심 UI 미렌더 등). build만으로는 못 잡던 사각.
            labels = [c[0] for c in checks]
            smoke_state, smoke_report = await self._runtime_smoke(ws, send)
            if smoke_state == "failed":
                return "failed", smoke_report
            if smoke_state == "passed":
                any_passed = True
                labels.append("runtime smoke")
            return ("passed", "검증 통과: " + ", ".join(labels)) if any_passed \
                else ("unavailable", "검증 실행 불가(모든 check가 unavailable)")
        finally:
            self._verify_cleanup(ws, before)

    async def _verify_gates(self, ws: str, session_id: str, send: EventSink) -> tuple[str, str]:
        """Acceptance Gate 검증 — verification 모듈로 위임(로직 분리, 인터페이스 유지)."""
        return await verification.verify_gates(ws, session_id, send)

    async def _verify_integration(self, ws: str, session_id: str, send: EventSink) -> tuple[str, str]:
        """Integration 검증 — leaf 작업들이 합쳐진 최종 상태에 대한 회귀 검증.

        단일 실행 구조에서는 "합쳐진 최종 상태" = 워크스페이스 전체다. 그래서 여기서
        generic 검증(build/test/smoke)을 한 번 더 돌려 회귀를 확인하고, 게이트 실패가
        남아 있으면 통합 실패로 처리한다. leaf verification(각 gate)과 명확히 구분된다.
        gate가 없으면 기존 흐름(integration 생략)을 그대로 탄다.
        """
        if not session_id:
            return "none", ""
        gates = await store.list_gates(session_id)
        if not gates:
            return "none", ""
        vstate, vreport = await self._verify(ws, send, stage="integration")
        if vstate == "failed":
            return "failed", "통합 검증 실패 — 최종 회귀(test/build) 실패:\n" + vreport[:600]
        failed = [g for g in gates if g.get("status") == "failed"]
        if failed:
            return "failed", "통합 검증 실패 — acceptance gate 미통과: " + \
                ", ".join(g["title"] for g in failed)
        passed = sum(1 for g in gates if g.get("status") == "passed")
        unverified = len(gates) - passed
        report = f"통합 검증 통과 — 최종 회귀(test/build) 통과, gate {passed}/{len(gates)} passed"
        if unverified:
            report += f", 미검증 {unverified}개"
        return "passed", report

    async def _gates_report(self, session_id: str) -> str:
        """미완료 gate 최종 보고 — verification 모듈로 위임(로직 분리, 인터페이스 유지)."""
        return await verification.gates_report(session_id)

    @staticmethod
    def _merge_memory_facts(existing: str, facts: list[str], cap: int = 4000) -> str | None:
        """ROOM_MEMORY에 새 durable 사실을 dedup·상한 적용해 병합한다(순수).
        추가할 게 없거나(중복) 상한을 넘으면 None(무한 성장·중복 방지)."""
        add = [f.strip() for f in facts
               if f.strip() and f.strip().lstrip("-").strip() not in existing]
        if not add:
            return None
        header = "" if "## 학습된 프로젝트 지식" in existing \
            else "\n## 학습된 프로젝트 지식 (FORGE 자동 적립)\n"
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        block = sep + header + "\n".join(add) + "\n"
        if len(existing) + len(block) > cap:
            return None
        return existing + block

    async def _extract_project_memory(self, session_id: str, ws: str, goal: str,
                                      files_changed: list, send: EventSink) -> None:
        """검증 통과 완료 시 **evidence에 결박된** durable 사실만 ROOM_MEMORY.md에 적립한다.

        LLM 출력 자체는 evidence가 아니다. utility 모델은 주어진 검증 사실을 압축만 하고,
        각 fact마다 근거 파일(source)과 gate/검증 명령(evidence)을 함께 내야 한다.
        그 후 memory_guard가 결정적으로 검증한다 — source가 이번 작업의 변경 파일인지,
        실제로 존재하는지, fact가 주장하는 토큰이 그 파일에 실제로 있는지.

        실측 오염 사례: 구현은 HTTP POST인데 "WebSocket/WebRTC 채널로 연결"이라고 적혀
        ROOM_MEMORY에 영속됐다. 이후 모든 세션 context에 실려 작업을 오염시킨다.
        원칙: 모르는 것 > 틀리게 기억하는 것. 애매하면 저장하지 않는다.

        best-effort — 실패해도 main task를 실패시키지 않는다(memory failure ≠ task failure).
        """
        if not settings.project_memory or not ws or not session_id or not files_changed:
            return
        try:
            gates = await store.list_gates(session_id)
            passed = [g["title"] for g in gates if g.get("status") == "passed"]
            methods = [g.get("verification_method", "") for g in gates
                       if g.get("status") == "passed" and g.get("verification_method")]
            # process-owned 근거가 없으면 적립하지 않는다. gate가 없으면 모델은 빈자리를
            # 일반론으로 채운다(실측: 이 워크스페이스에 없는 명령이 사실로 적립됐다).
            if not passed or not methods:
                return

            rel_changed = self._relative_changed(ws, files_changed)
            if not rel_changed:
                return
            evidence_keys = passed + methods

            src = (f"목표: {goal[:200]}\n"
                   f"통과한 요구사항(evidence로 인용 가능): {', '.join(passed)}\n"
                   f"검증 명령(evidence로 인용 가능): {'; '.join(m[:80] for m in methods[:5])}\n"
                   f"이번에 변경된 파일(source로 인용 가능): {', '.join(rel_changed[:20])}")
            prompt = [
                {"role": "system", "content":
                    "너는 새로운 사실을 생각해내지 않는다. 주어진 검증 사실을 압축만 한다.\n"
                    "이 프로젝트에서 앞으로 재사용할 durable 지식을 최대 3개까지 JSON 배열로 출력하라.\n"
                    '형식: [{"fact": "...", "source": "변경된 파일 경로 중 하나", "evidence": '
                    '"통과한 요구사항 또는 검증 명령 중 하나"}]\n'
                    "규칙:\n"
                    "- 입력에 명시된 사실만 사용한다. 추론·보간·일반론 금지.\n"
                    "- source는 위 '변경된 파일' 목록에 있는 경로만 쓴다.\n"
                    "- fact가 언급하는 함수명·API 경로·기술 이름은 그 source 파일에 실제로 있어야 한다.\n"
                    "- 확실하지 않으면 그 fact를 빼라. 아무것도 없으면 [] 만 출력.\n"
                    "- 좋은 예: 빌드/테스트 명령, API 경로, 코딩 규약, 반복되는 프로젝트 특유 절차.\n"
                    "- 나쁜 예: 이번 한 번의 수정 내용, 일반 프로그래밍 상식, 추측한 아키텍처."},
                {"role": "user", "content": src},
            ]
            parts: list[str] = []
            async for d in self._adapter_for(self.router.utility_model).stream_chat(prompt):
                if d.get("content"):
                    parts.append(d["content"])
            candidates = self._parse_memory_candidates("".join(parts))
            if not candidates:
                return

            path = Path(ws) / "ROOM_MEMORY.md"
            existing = path.read_text(encoding="utf-8") if path.exists() else ""

            def read_source(rel: str) -> str | None:
                try:
                    f = Path(ws) / rel
                    return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else None
                except Exception:
                    return None

            await send("project_memory_candidate", {"count": len(candidates)})
            accepted: list[str] = []
            rejected: list[dict] = []
            merged_existing = existing
            for cand in candidates:
                ok, why = memory_guard.validate_candidate(
                    cand, workspace=ws, changed_files=rel_changed,
                    evidence_keys=evidence_keys, existing_memory=merged_existing,
                    read_source=read_source)
                if not ok:
                    rejected.append({"fact": str(cand.get("fact", ""))[:120], "reason": why})
                    continue
                block = memory_guard.format_fact(cand)
                accepted.append(block)
                merged_existing += block  # 같은 배치 안 중복도 막는다
            if rejected:
                await send("project_memory_rejected", {"items": rejected})
            if not accepted:
                return

            merged = self._merge_memory_facts(existing, accepted)
            if merged is None:
                return
            path.write_text(merged, encoding="utf-8")
            await send("project_memory_saved", {"count": len(accepted)})
        except Exception as err:
            error_log.record("project_memory", str(err), session_id)

    @staticmethod
    def _relative_changed(ws: str, files_changed: list) -> list[str]:
        """변경 파일을 워크스페이스 기준 상대 경로로 정규화한다(중복 제거)."""
        out: list[str] = []
        for raw in files_changed or []:
            q = str(raw or "").strip()
            if not q:
                continue
            if os.path.isabs(q):
                try:
                    q = os.path.relpath(q, ws)
                except ValueError:
                    continue
            q = os.path.normpath(q)
            if q.startswith("..") or q in out:
                continue
            out.append(q)
        return out

    @staticmethod
    def _parse_memory_candidates(text: str) -> list[dict]:
        """모델 출력에서 candidate JSON 배열만 뽑는다. 형식이 깨지면 빈 목록(저장 안 함)."""
        t = (text or "").strip()
        if not t:
            return []
        m = re.search(r"\[.*\]", t, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for it in data[:3]:
            if isinstance(it, dict) and it.get("fact"):
                out.append({"fact": str(it.get("fact", "")),
                            "source": str(it.get("source", "")),
                            "evidence": str(it.get("evidence", ""))})
        return out

    @staticmethod
    def _effective_thinking(thinking, counters) -> bool:
        """이 호출에 실제로 적용될 thinking 여부(순수). 같은 role invocation에서 이전 step이
        reasoning 400 폴백을 겪었으면(counters["reasoning_replay_failed"]) thinking을 끈다.
        사전 compaction·breakdown·전송이 모두 이 한 판단을 공유해 추정본과 전송본을 일치시킨다."""
        return bool(thinking) and not bool(counters and counters.get("reasoning_replay_failed"))

    @staticmethod
    def _should_keep_reasoning(adapter, thinking, tool_schemas) -> bool:
        """이 호출에서 히스토리의 reasoning_content를 전송본에 유지할지(순수).
        DeepSeek V4 계약: thinking+tools + provider가 replay를 요구하면 유지, 아니면 제거."""
        return (bool(thinking) and bool(tool_schemas)
                and getattr(adapter, "requires_reasoning_replay", False))

    @staticmethod
    def _msg_text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                x.get("text", "") for x in content
                if isinstance(x, dict) and x.get("type") == "text"
            )
        return str(content or "")

    @staticmethod
    def build_context_tree(role, send_proj, skills, room_memory, plan, keep_reasoning) -> dict:
        """계층형 context 사용 트리(순수·근사). 전송 payload를 카테고리별 노드로 분해해 무엇이
        컨텍스트를 차지하는지 드러낸다. 각 노드는 토큰·문자 수만 담고 원문·tool args는 넣지
        않는다(민감정보 비노출). 노드별 measured_tokens는 null이다 — 실측은 provider usage로
        전체 단위만 존재하므로 노드에 섞어 허위 정밀도를 만들지 않는다. 큰 tool 결과는 원문을
        다시 싣지 않고 tool_store 참조(content_ref)만 남긴다. 어떤 이상 입력에도 예외를 던지지
        않아(호출측 try 불필요) breakdown 실패가 agent 실행을 막지 못한다."""
        try:
            return AgentRuntime._build_context_tree_impl(
                role, send_proj, skills, room_memory, plan, keep_reasoning)
        except Exception:
            return {"tree": [], "total_est": 0, "measured_total": None,
                    "budget": settings.logical_budget, "max_output": settings.max_output_tokens}

    @staticmethod
    def _build_context_tree_impl(role, send_proj, skills, room_memory, plan, keep_reasoning) -> dict:
        _tr_re = re.compile(r"read_tool_result\('(tr_[0-9a-f]+)'\)")
        nid = [0]

        def node(category, label, est_tokens, chars, *, children=None, content_ref=None):
            nid[0] += 1
            return {
                "id": f"ctx-{nid[0]}",
                "category": category,
                "label": label,
                "estimated_tokens": int(est_tokens),
                "measured_tokens": None,   # 노드 단위 실측 없음 — 전체는 provider usage로 별도
                "characters": int(chars),
                "children": children or [],
                "content_available": content_ref is not None,
                "content_ref": content_ref,
            }

        def text_node(category, label, text, *, content_ref=None):
            return node(category, label, _est_tokens(text), len(text), content_ref=content_ref)

        tree: list[dict] = []
        # 고정 프리픽스: system(base) / rules(role) / memory / skills / plan
        tree.append(text_node("system", "System 기본 프롬프트", BASE_PROMPT))
        tree.append(text_node("rules", f"{role} 역할 지침", _load_role(role)))
        mem = (room_memory or "") + _load_global_memory()
        if mem:
            tree.append(text_node("memory", "메모리(방·전역)", mem))
        if skills:
            tree.append(text_node("skills", "축적 Skill", skills))
        if plan:
            tree.append(text_node("plan", "외부 계획(Planner)", plan))

        # 동적 히스토리: 카테고리별로 집계하되 tool call/result는 개별 자식 노드로.
        conv_tok = summ_tok = reason_tok = 0
        conv_chars = summ_chars = reason_chars = 0
        img_count = 0
        call_children: list[dict] = []
        result_children: list[dict] = []
        call_name_by_id: dict[str, str] = {}
        call_i = res_i = 0
        for m in (send_proj or []):
            if not isinstance(m, dict):
                continue
            role_m = m.get("role")
            content = m.get("content", "")
            text = AgentRuntime._msg_text(content)
            if isinstance(content, list):
                img_count += sum(1 for x in content
                                 if isinstance(x, dict) and x.get("type") == "image_url")
            if role_m == "user" and text.startswith("[이전 작업 요약"):
                summ_tok += _est_tokens(text); summ_chars += len(text)
            elif role_m == "tool":
                res_i += 1
                nm = call_name_by_id.get(m.get("tool_call_id"), "tool")
                mo = _tr_re.search(text)
                result_children.append(
                    text_node("tool_results", f"{nm} #{res_i} 결과", text,
                              content_ref=mo.group(1) if mo else None))
            else:
                conv_tok += _est_tokens(text); conv_chars += len(text)
                if keep_reasoning and isinstance(m.get("reasoning_content"), str):
                    reason_tok += _est_tokens(m["reasoning_content"])
                    reason_chars += len(m["reasoning_content"])
                tcs = m.get("tool_calls")
                if isinstance(tcs, list):
                    for tc in tcs:
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function") or {}
                        nm = fn.get("name", "tool")
                        if tc.get("id"):
                            call_name_by_id[tc["id"]] = nm
                        call_i += 1
                        # args 원문은 넣지 않고 문자 수만(토큰 추정 근거).
                        call_children.append(
                            text_node("tool_calls", f"{nm} #{call_i}", fn.get("arguments", "") or ""))

        if summ_chars:
            tree.append(node("summary", "이전 작업 요약(compaction)", summ_tok, summ_chars))
        if conv_chars:
            tree.append(node("conversation", "대화(user·assistant)", conv_tok, conv_chars))
        if keep_reasoning and reason_chars:
            tree.append(node("reasoning", "추론(reasoning_content)", reason_tok, reason_chars))
        if call_children:
            tree.append(node("tool_calls", "도구 호출",
                             sum(c["estimated_tokens"] for c in call_children),
                             sum(c["characters"] for c in call_children), children=call_children))
        if result_children:
            tree.append(node("tool_results", "도구 결과",
                             sum(c["estimated_tokens"] for c in result_children),
                             sum(c["characters"] for c in result_children), children=result_children))
        if img_count:
            tree.append(node("images", f"이미지 입력 {img_count}장",
                             img_count * settings.image_input_token_estimate, 0))

        # 예약 출력(입력 컨텍스트가 아니라 응답용으로 남겨둔 예산) — total_est에는 넣지 않는다.
        tree.append(node("reserved_output", "예약 출력 토큰", settings.max_output_tokens, 0))

        total_est = sum(n["estimated_tokens"] for n in tree if n["category"] != "reserved_output")
        return {
            "tree": tree,
            "total_est": total_est,
            "measured_total": None,      # provider usage(measured)로 별도 — 노드와 섞지 않음
            "budget": settings.logical_budget,
            "max_output": settings.max_output_tokens,
        }

    @staticmethod
    def _image_stats(projected) -> dict:
        """전송 payload의 이미지 입력 raw 계측(추정 토큰과 혼동 방지용). data URI 원문은 남기지
        않고 개수와 대략 bytes만 센다(추후 provider usage와 보정). image_url content만 대상."""
        count = 0
        approx_bytes = 0
        for m in projected:
            c = m.get("content")
            if not isinstance(c, list):
                continue
            for x in c:
                if isinstance(x, dict) and x.get("type") == "image_url":
                    count += 1
                    url = (x.get("image_url") or {}).get("url", "")
                    if isinstance(url, str) and ";base64," in url:
                        b64 = url.split(";base64,", 1)[1]
                        approx_bytes += len(b64) * 3 // 4  # base64 → 원본 bytes 근사(길이만 사용)
        return {"count": count, "bytes": approx_bytes}

    @staticmethod
    def _estimate_context_areas(system_msg, projected, skills, room_memory, keep_reasoning) -> dict:
        """최종 전송 payload 기준 영역별 토큰 추정(순수). projected는 fold/strip이 적용된
        전송 형태를 받는다. content만 세던 옛 계산이 reasoning_content와 tool_call arguments를
        누락해 실측과 크게 어긋나던 것을 바로잡는다. reasoning은 keep_reasoning일 때만 포함
        (전송본에서 실제로 벗겨지면 0). compaction 판단과 debug breakdown이 이 함수를 공유한다.
        텍스트 영역은 문자 기반 추정이고, image_inputs는 이미지당 고정 추정(정확도가 낮다 —
        base64 길이가 아니라 이미지 수 × 추정 토큰). 절대값은 추정이며 실측 총량은 provider
        usage(measured)가 최종 권위다."""
        system_total = _est_tokens(AgentRuntime._msg_text(system_msg.get("content", "")))
        skills_t = _est_tokens(skills or "")
        memory_t = _est_tokens(room_memory or "") + _est_tokens(_load_global_memory())
        base_role_t = max(0, system_total - skills_t - memory_t)  # base+role = system − memory − skills
        hist_t = tool_t = reason_t = args_t = img_count = 0
        for m in projected:
            text = AgentRuntime._msg_text(m.get("content", ""))
            if m.get("role") == "tool":
                tool_t += _est_tokens(text)
            else:
                hist_t += _est_tokens(text)
            if keep_reasoning and isinstance(m.get("reasoning_content"), str):
                reason_t += _est_tokens(m["reasoning_content"])
            for tc in (m.get("tool_calls") or []):
                args_t += _est_tokens((tc.get("function") or {}).get("arguments", "") or "")
            c = m.get("content")
            if isinstance(c, list):
                img_count += sum(1 for x in c
                                 if isinstance(x, dict) and x.get("type") == "image_url")
        # 이미지는 base64 길이가 아니라 이미지당 고정 추정(DeepSeek vision 상한). estimated.
        image_t = img_count * settings.image_input_token_estimate
        total = base_role_t + skills_t + memory_t + hist_t + tool_t + reason_t + args_t + image_t
        return {
            "system_base_role": base_role_t,
            "memory": memory_t,
            "skills": skills_t,
            "history_content": hist_t,
            "tool_results": tool_t,
            "reasoning_content": reason_t,
            "tool_call_arguments": args_t,
            "image_inputs": image_t,
            "total_est": total,
        }

    def _to_send_projection(self, projected: list[dict], has_image: bool) -> list[dict]:
        """모델에 보낼 최종 projection(system 제외): orphan tool 제거 → write_file 접기 →
        image 처리. 원본은 불변. est/breakdown/실제 전송이 모두 이 형태를 기준으로 한다."""
        p = self._drop_orphan_tools(projected)
        p = self._fold_old_write_args(p, WRITE_ARGS_KEEP_RECENT_MESSAGES)
        if has_image:
            return [
                {**m, "content": [_to_data_uri_item(c) for c in m["content"]]}
                if isinstance(m.get("content"), list) else m
                for m in p
            ]
        return self._strip_images(p)

    async def _precompact(self, session_id, all_messages, system_msg, skills, room_memory,
                          keep_reasoning, on_compaction, has_image=False) -> list[dict]:
        """전송 전 사전 압축: 실제 전송 형태(fold·strip·has_image image 처리 포함)로 추정한 total_est가
        임계를 넘으면 미리 압축해 초과 호출 자체를 막는다. content만 세던 옛 판단은 reasoning·tool
        arguments·이미지를 놓쳐(실측상 히스토리 대부분) 사전 압축이 헛돌던 것을 바로잡는다.
        압축이 일어나면 on_compaction(covered)를 await한다. 최종 projected(변환 전)를 반환."""
        projected = self._project(all_messages, session_id)
        if not session_id:
            return projected
        for _ in range(3):
            payload = self._to_send_projection(projected, has_image)
            areas = self._estimate_context_areas(system_msg, payload, skills, room_memory, keep_reasoning)
            if areas["total_est"] <= settings.logical_budget * CONTEXT_COMPACT_RATIO:
                break
            if not await self._compact(all_messages, session_id):
                break
            await on_compaction(self._compaction[session_id]["covered"])
            projected = self._project(all_messages, session_id)
        return projected

    def _store_context_breakdown(self, session_id, role, areas: dict,
                                 image_stats: dict | None = None, tree: dict | None = None):
        """이미 계산된 areas(전송 payload 기준)를 debug view용으로 저장한다. 이미지 raw 계측
        (개수·bytes)은 추정 토큰과 구분해 image_raw로 남긴다 — data URI 원문은 저장하지 않는다.
        계층형 tree가 있으면 함께 저장한다(기존 areas는 하위 호환으로 유지)."""
        try:
            budget = settings.logical_budget
            total = areas.get("total_est", 0)
            entry = {
                "role": role,
                "areas": {k: v for k, v in areas.items() if k != "total_est"},
                "total_est": total,
                "budget": budget,
                "pct_est": round(total / budget * 100, 1) if budget else 0,
            }
            if image_stats and image_stats.get("count"):
                entry["image_raw"] = {
                    "count": image_stats.get("count", 0),
                    "bytes": image_stats.get("bytes", 0),
                    "est_per_image": settings.image_input_token_estimate,
                    "estimated": True,
                }
            if tree and tree.get("tree"):
                entry["tree"] = tree["tree"]
                entry["max_output"] = tree.get("max_output")
                entry["measured_total"] = tree.get("measured_total")
            self._last_context[session_id] = entry
        except Exception as err:
            error_log.record("context_breakdown", str(err), session_id)

    def get_context_breakdown(self, session_id: str) -> dict:
        return self._last_context.get(session_id, {})

    async def _runtime_smoke(self, ws: str, send: EventSink) -> tuple[str, str]:
        """self-repo(FORGE 자신)일 때만: 빌드된 앱을 headless로 로드해 런타임 검증한다.
        반환 (state, report). failed=런타임 크래시/핵심 미렌더, unavailable=대상 아님/실행 불가.
        console.error는 SW·PWA 잡음이 많아 무시하고, uncaught 예외(pageerror)와 핵심 셀렉터
        렌더만 본다(false positive 억제). 8790에 앱이 떠 있어야 하며, StaticFiles라 방금 빌드된
        dist가 재시작 없이 서빙된다."""
        import os as _os
        if _os.path.realpath(ws) != _os.path.realpath(str(_REPO_ROOT)):
            return "unavailable", ""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "unavailable", "playwright 미설치"
        try:
            errors: list[str] = []
            health_status = None
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                try:
                    await page.goto("http://127.0.0.1:8790",
                                    wait_until="networkidle", timeout=20000)
                    header = await page.locator("header").count()
                    composer = await page.locator(".composer-input").count()
                    # 축 A — 서버 생존/응답성. 정적 렌더만 보면 백엔드가 먹통이어도(오늘 사고)
                    # page.goto 타임아웃이 unavailable로 새어 "검증 안 함"이 된다. health가
                    # 짧은 타임아웃 안에 200인지 브라우저 안에서 직접 확인해 failed로 잡는다.
                    try:
                        health_status = await page.evaluate(
                            "() => fetch('/api/health', {cache:'no-store'})"
                            ".then(r => r.status).catch(() => 0)")
                    except Exception:
                        health_status = 0
                finally:
                    await browser.close()
            if errors:
                return "failed", "런타임 스모크 실패 — 앱에서 uncaught 예외:\n" + "\n".join(errors[:8])
            if not header or not composer:
                return "failed", ("런타임 스모크 실패 — 핵심 UI 미렌더 "
                                  f"(header={header}, composer={composer})")
            if health_status != 200:
                return "failed", ("런타임 스모크 실패 — 백엔드가 응답하지 않음 "
                                  f"(/api/health={health_status}). 서버 생존/응답성 실패.")
            await send("verify_start", {"checks": ["runtime smoke"]})
            return "passed", "런타임 스모크 통과(로드·핵심 렌더·백엔드 응답·uncaught 예외 0)"
        except Exception as err:
            # 8790 미기동·타임아웃 등은 검증 불가로 처리(거짓 failed 방지).
            return "unavailable", f"런타임 스모크 실행 불가: {err}"

    async def run(
        self,
        history: list[dict],
        emit: EventSink,
        session_id: str = "",
        workspace: str | None = None,
    ) -> list[dict]:
        ws = workspace or settings.workspace
        # 이 run의 식별자 — 승인 audit·세션/run 범위 정리에 쓴다. run() 1회(세션당 선점)마다
        # 새로 만들며, resume도 새 run이라 새 run_id를 받는다. cleanup_session에서 정리한다.
        if session_id:
            self._run_ids[session_id] = uuid.uuid4().hex
        # 재시작 내성: _last_seq는 in-memory라 서버 재시작 시 비어 있다. 세션의 seq를 처음
        # 쓸 때 eventlog에서 그 세션의 마지막 seq를 읽어 seed — 이미 로그에 쌓인 높은 seq와
        # 충돌해 폴링 dedup이 깨지는 것을 막는다.
        if session_id not in self._last_seq:
            _prev = eventlog.tail(session_id, limit=1)
            self._last_seq[session_id] = _prev[0]["seq"] if _prev else 0
        seq = self._last_seq[session_id]

        async def send(event_type: str, data: dict[str, Any]) -> None:
            nonlocal seq
            seq += 1
            self._last_seq[session_id] = seq
            # 라이브 상태 갱신(스트림이 끊겨도 /status로 지금 뭘 하는지 조회 가능) + durable 이벤트 로그.
            fields: dict[str, Any] = {"last_event": event_type}
            if event_type == "role_start":
                fields["role"] = data.get("role", "")
            activity = self._activity_label(event_type, data)
            if activity:
                fields["activity"] = activity
            self._status_update(session_id, **fields)
            eventlog.record(session_id, seq, event_type, data)
            await emit({"seq": seq, "type": event_type, "data": data})

        self._cancel_sessions.discard(session_id)
        self._cancel_events.pop(session_id, None)  # 이전 run의 취소 이벤트 잔재 제거
        self._run_cost[session_id] = 0.0  # 예산 가드레일 — 이 run의 누적 비용 리셋
        self._injections.pop(session_id, None)
        if session_id:
            self._running_sessions.add(session_id)

        goal = ""
        full_request = ""   # Task IR 인터프리터용 원문(이미지 턴은 대상 아님)
        for m in reversed(history):
            if m.get("role") == "user":
                c = m.get("content", "")
                goal = str(c)[:200]
                full_request = c if isinstance(c, str) else ""
                break
        state: dict[str, Any] = {"goal": goal, "files_changed": [], "errors": []}
        recent_calls: list[str] = []
        all_messages: list[dict] = [*history]
        # 압축 요약 복원 — run마다 메모리가 비므로 DB에서 되살린다. 이게 없으면 이전 run의
        # 압축이 통째로 버려져 전체 히스토리를 다시 보내고, 압축이 영원히 누적되지 않는다.
        if session_id and session_id not in self._compaction:
            saved = await store.get_session_compaction(session_id)
            if saved and saved["covered"] <= len(all_messages):
                self._compaction[session_id] = saved
        room_memory = _load_room_memory(ws)
        req_block = ""   # Task IR requirement 블록 — 코드 경로 진입 후 채운다(대화 턴 제외).
        # Security preflight — 주입 설정 표면/추적 시크릿을 결정적 스캔. 관찰 전용(fail-open):
        # 실행을 막지 않고 findings가 있을 때만 이벤트 한 건 표면화한다. 어떤 예외도 run에
        # 영향을 주지 않는다. HIGH→approval 게이팅은 의도적으로 후속(벤치 재측정 필요).
        try:
            tracked: list[str] = []
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "-C", ws, "ls-files", "-z",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
                tracked = [p for p in out.decode("utf-8", "replace").split("\0") if p]
            except (OSError, asyncio.TimeoutError, ValueError):
                tracked = []  # git 없거나 느리면 tracked 스캔만 생략(injection 스캔은 유지)
            _pf = security_preflight.scan_workspace(ws, tracked_files=tracked)
            if _pf:
                _level, _line = security_preflight.summarize(_pf)
                await send("security_preflight", {
                    "level": _level, "summary": _line,
                    "findings": [{"severity": f.severity, "category": f.category,
                                  "path": f.path, "detail": f.detail} for f in _pf[:20]],
                })
        except Exception as _pf_err:  # noqa: BLE001 — preflight는 절대 run을 깨지 않는다
            error_log.record("security_preflight", str(_pf_err), "")
        # 요청과 관련된 skill만 선택 삽입(전량 삽입 금지 — skill이 많아질수록 절감).
        skills = _select_skills(ws, goal)
        skill_names = re.findall(r"### skill: (.+)", skills)
        skill_count = len(skill_names)
        skill_csv = ", ".join(skill_names)

        # 이미지가 포함된 요청이면 Developer를 vision 모델로 실행한다(별도 Vision 호출 없이 —
        # Developer가 이미지를 직접 받아 분석·구현). role은 developer로 기록, 모델만 vision.
        # 이번 턴(가장 최근 user 메시지)만 본다 — 세션 전체를 보면 예전 스크린샷 하나가
        # 이후 무관한 텍스트 작업까지 계속 vision으로 끌고 간다(실측 버그).
        has_image = _turn_has_image(history)

        step_base = 0

        async def record(role: str, p: int, c: int, route: dict) -> None:
            if not session_id:
                return
            elapsed_ms = int((time.monotonic() - route.get("_start", time.monotonic())) * 1000)
            await store.save_agent_run(
                session_id,
                role,
                route.get("model", ""),
                p,
                c,
                route.get("thinking", False),
                route.get("reasoning_effort", ""),
                route.get("cache_hit", 0),
                route.get("cache_miss", 0),
                route.get("model_calls", 0),
                route.get("tool_calls", 0),
                route.get("retries", 0),
                route.get("compactions", 0),
                elapsed_ms,
                skill_count,
                skill_csv,
                route.get("tool_raw", 0),
                route.get("tool_visible", 0),
            )

        async def finish(status: str, content: str = "", summary: dict | None = None) -> None:
            # 성공 완료 시 하네스가 장부를 마감한다 — 모델이 잊어도 신뢰성 보장:
            # 남은 task done 처리(칸반), 변경 자동 commit+push(커밋 누락 방지).
            # completed(검증됨)와 completed_unverified(검증 대상 없음) 둘 다 마감 대상.
            # verification_failed는 여기 안 걸려 절대 커밋되지 않는다(invariant).
            if status in ("completed", "completed_unverified"):
                # 태스크 마감은 '완료 상태'이면 무조건 한다 — 변경이 이전 run에서 났고 마지막
                # 턴이 무변경(예: "끝났니?" 확인)이면, run 단위 files_changed 게이트가 태스크를
                # working에 가둬 멈춘 것처럼 보였다. 완료면 칸반도 완료로 마감한다.
                await self._finalize_tasks(session_id, send)
                # 자동 커밋은 이번 run에 실제 변경이 있을 때만(빈 커밋 방지).
                # push는 completed(충분히 검증됨)만 — completed_unverified(검증 대상 없음/일부 게이트
                # 미검증)는 로컬 commit만 하고 origin에 자동 배포하지 않는다(검증된 것만 배포 경로).
                if state["files_changed"]:
                    committed, pushed = await self._autocommit(
                        ws, goal, send, state["files_changed"], push=(status == "completed"))
                    # 배포 상태는 추측하지 않는다 — 실제 commit/push 결과만 사용자에게 말한다.
                    # (리포트를 미리 만들면 push가 실패해도 "push 완료"라고 보고한다.)
                    if summary is not None:
                        summary["commit_status"] = committed
                        summary["push_status"] = pushed
                # 검증 통과 완료만 durable 프로젝트 지식으로 적립(§6) — 미검증은 오염 방지로 제외.
                if status == "completed":
                    await self._extract_project_memory(session_id, ws, goal,
                                                       state["files_changed"], send)
            else:
                # 비완료 종료: testing/working에 남은 task를 blocked로 강등(칸반이 '진행 중'처럼
                # 보이지 않게). done으로 마감하지도, 커밋하지도 않는다(invariant 유지).
                await self._fail_pending_tasks(session_id, send)
            # 최종 문구는 summary(process-owned 사실)에서 deterministic하게 만든다 —
            # LLM을 다시 부르지 않고, 모델의 self-report를 근거로 쓰지 않는다.
            if summary is not None:
                content = self.format_completion_summary(summary)
                # history에 남긴다 — 안 남기면 새로고침 시 권위 있는 보고는 사라지고
                # 모델의 자기서술만 durable하게 남는다(정확히 반대여야 한다).
                all_messages.append({"role": "assistant", "content": content})
                if session_id:
                    try:
                        await store.save_history(session_id, all_messages)
                    except Exception as err:
                        error_log.record("final_report_save", str(err), session_id)
            # gate 커버리지 계측 — 어떤 경로로 완료했는지 분류해 남긴다.
            # docs/proposal/gate-coverage-enforcement.md
            if session_id:
                _gates = await store.list_gates(session_id)
                _n = len(_gates)
                await send("gate_coverage", {
                    "status": status,
                    "gates": _n,
                    "passed": sum(1 for g in _gates if g.get("status") == "passed"),
                    "files_changed": len(state["files_changed"]),
                    "generic_only": _n == 0 and bool(state["files_changed"]),
                    "coverage": _coverage_kind(
                        _n, state["files_changed"],
                        bool(state.get("gate_recovery_ran")), route_kind == "code"),
                })
                # Task IR requirement ↔ gate 대조. Task IR이 있을 때만(완료 판정에도 반영됨).
                # false_completion(요구사항을 놓친 채 완료) 후보를 드러낸다.
                _reqs = self._task_ir_reqs.pop(session_id, None)
                if _reqs:
                    await send("traceability", traceability.compute_traceability(_reqs, _gates))
            # done 이벤트를 보내면서 세션 final_status를 영속화(성공 정의·집계 기준).
            if session_id:
                await store.set_session_final_status(session_id, status)
            # 학습 후보 수집(적용 없음) — done보다 먼저 보내 같은 스트림에 실린다.
            await self._reflect(session_id, ws, status, send)
            data = {"status": status}
            if content:
                data["content"] = content
            await send("done", data)

        # 0. 라우터 — 방 모드가 정해져 있으면 triage를 건너뛴다(비용·오분류 제거).
        #    "chat"=항상 대화(읽기전용), "work"=항상 작업(검증·커밋), ""=triage 자동 분류.
        _room = await store.get_room(session_id) if session_id else None
        _mode = (_room or {}).get("mode", "") if _room else ""
        # 선제 compaction — 재시작·긴 세션은 첫 model 호출이 예산을 넘겨 모델 한도에 걸린다.
        # in-memory 요약은 재시작 시 유실되므로, 저장된 used_tokens(마지막 실측)로 미리 판단해
        # 첫 호출 전에 오래된 대화를 요약해 둔다. 그래야 첫 대화부터 컨텍스트가 줄어든다.
        if (session_id and _room
                and _room.get("used_tokens", 0) > settings.logical_budget * CONTEXT_COMPACT_RATIO
                and session_id not in self._compaction):
            if await self._compact(all_messages, session_id):
                await send("compaction", {"covered": self._compaction[session_id]["covered"]})
        if _mode == "chat":
            route_kind = "chat"
            # 채팅 방인데 요청이 코드 작업으로 판단되면 작업 모드 전환을 제안한다.
            # 승인하면 이 방을 work로 바꾸고(다음부터 자동) 이번 요청도 작업 경로로 처리한다.
            rk, tp, tc = await self._triage(all_messages)
            await record("triage", tp, tc, {"model": self.router.triage_model, "model_calls": 1})
            if rk == "code":
                ws_ok = _room and _room.get("workspace_path") and _room["workspace_path"] not in ("/", os.path.expanduser("~"))
                ans = await self._ask_user({
                    "question": "이 요청은 코드 변경이 필요해 보입니다. 작업 모드로 전환할까요? (검증·커밋이 켜집니다)"
                    if ws_ok else "코드 작업 같지만 이 방은 워크스페이스가 없어 작업 모드로 못 바꿉니다. 채팅으로 답할까요?",
                    "options": ["작업 모드로 전환", "채팅 유지"] if ws_ok else ["채팅으로 답"],
                }, send, session_id)
                if ws_ok and ans and "전환" in ans:
                    await store.update_room_mode(session_id, "work")
                    await send("mode_changed", {"mode": "work"})
                    route_kind = "code"
        elif _mode == "work":
            route_kind = "code"
        else:
            route_kind, tp, tc = await self._triage(all_messages)
            await record("triage", tp, tc, {"model": self.router.triage_model, "model_calls": 1})
        if route_kind == "chat":
            status, p, c, route = await self._run_role(
                "chat", all_messages, send, session_id, ws, state, recent_calls,
                step_base, room_memory, tools=CHAT_TOOLS, skills=skills,
            )
            await record("chat", p, c, route)
            # 자동 분류가 chat으로 오분류했는데 모델이 코드 변경을 시도했다면(wanted_mutation),
            # 막다른 거부-반복으로 끝내지 말고 작업 모드 전환을 제안한다. 수락하면 이 요청을
            # 그대로 작업 경로로 이어 처리하고, 이 방을 work로 바꿔 다음부터 자동 전환한다.
            transitioned = False
            if route.get("wanted_mutation"):
                ws_ok = (_room and _room.get("workspace_path")
                         and _room["workspace_path"] not in ("/", os.path.expanduser("~")))
                if ws_ok:
                    ans = await self._ask_user({
                        "question": "이 요청은 코드 변경이 필요해 보입니다. 작업 모드로 전환할까요? (검증·커밋이 켜집니다)",
                        "options": ["작업 모드로 전환", "채팅 유지"],
                    }, send, session_id)
                    if ans and "전환" in ans:
                        await store.update_room_mode(session_id, "work")
                        await send("mode_changed", {"mode": "work"})
                        route_kind = "code"
                        transitioned = True
            if not transitioned:
                await finish("completed" if status == "done"
                             else _STATUS_CODES.get(status, "failed"),
                             "" if status == "done" else self._finish_message(status))
                return all_messages
            # transitioned → 아래 작업(code) 경로로 계속 진행

        # Task IR 해석은 코드 경로에서만 — 대화·질문 턴엔 gate도 완료 판정도 없어 인터프리터가
        # 얻는 게 없고, 대화를 억지 requirement로 뽑아 traceability를 false_completion 후보로
        # 오염시켰다(실측: chat 세션 4턴 전부). 여기(route_kind=="code" 확정)서만 돌린다.
        await self._maybe_interpret(full_request, send, session_id)
        req_block = _requirements_block(
            self._task_ir_reqs.get(session_id) if session_id else None)

        # 1. 에이전트 모드 결정 — 사용자 명시(multi/single)가 최우선, auto는 복잡도 기반 자동.
        mode = self.get_agent_mode(session_id)
        complexity = _estimate_complexity(goal, all_messages)
        use_multi = (mode == "multi") or (mode == "auto" and complexity == "complex")
        await send("agent_mode", {
            "mode": "multi" if use_multi else "single",
            "agent_mode": mode,
            "complexity": complexity,
        })

        # 모델 티어(사용자 선택): pro=항상 pro / flash=승격 없음 / auto=막히면 pro 승격.
        tier = self._model_tier.get(session_id, "auto")
        always_pro = tier == "pro" or settings.developer_pro

        async def _run_developer(plan: str = ""):
            """Developer 실행 + 막힘 시 pro 승격 상한 루프(MAX_ESCALATIONS로 캡).
            multi 모드에서도 승격은 그대로 동작한다. plan이 있으면 system에 주입."""
            nonlocal step_base
            status, p, c, route = await self._run_role(
                "developer", all_messages, send, session_id, ws, state, recent_calls,
                step_base, room_memory, skills=skills, escalate=always_pro,
                has_image=has_image, plan=plan, requirements=req_block,
            )
            await record("developer", p, c, route)
            escalations = 0
            while (tier == "auto" and not always_pro
                   and status in ("max_steps", "repeated") and escalations < MAX_ESCALATIONS):
                escalations += 1
                step_base += DEVELOPER_MAX_STEPS
                status, p, c, route = await self._run_role(
                    "developer", all_messages, send, session_id, ws, state, recent_calls,
                    step_base, room_memory, skills=skills, escalate=True,
                    has_image=has_image, plan=plan, requirements=req_block,
                )
                await record("developer", p, c, route)
            return status

        plan = ""
        if use_multi:
            # 2a. Planner — 계획 수립(최근 맥락 + 읽기 전용 도구만, flash).
            #     전체 컨텍스트를 재전송하지 않아 과거 planner 비용 문제가 재발하지 않는다.
            planner_msgs = _planner_context(all_messages)
            p_status, p, c, route = await self._run_role(
                "planner", planner_msgs, send, session_id, ws, state, recent_calls,
                step_base, room_memory, tools=READ_ONLY_TOOL_SCHEMAS, skills=skills,
                persist=False,
            )
            await record("planner", p, c, route)
            step_base += PLANNER_MAX_STEPS
            plan = _last_assistant_text(planner_msgs) if p_status == "done" else ""

            if p_status == "done" and plan:
                # 칸반 강제 — 계획 단계를 태스크로 자동 등록한다. 모델이 update_tasks를 안 불러도
                # 칸반이 비지 않는다(다중 파일 작업인데 태스크 0이던 문제). 이후 developer가
                # update_tasks로 갱신하면 merge_tasks가 신원을 맞춰 이어간다.
                auto_tasks = _plan_to_tasks(plan)
                if auto_tasks and session_id and not await store.list_tasks(session_id):
                    saved = await store.replace_tasks(session_id, auto_tasks)
                    await send("task_update", {"tasks": saved})
                # 2b. Developer — 계획을 받아 실행(+승격 루프).
                status = await _run_developer(plan)
                if status == "done":
                    # 2c. Reviewer — 독립 검증(flash). 문제 시 Developer가 1회 수정
                    #     (리뷰↔수정 왕복 churn 방지 — 리뷰 루프는 최대 1회).
                    reviewer_msgs = _reviewer_context(all_messages, plan)
                    r_status, p, c, route = await self._run_role(
                        "reviewer", reviewer_msgs, send, session_id, ws, state, recent_calls,
                        step_base, room_memory, tools=READ_ONLY_TOOL_SCHEMAS, skills=skills,
                        persist=False,
                    )
                    await record("reviewer", p, c, route)
                    step_base += REVIEWER_MAX_STEPS
                    # reviewer.md 규약: 마지막 줄이 정확히 PASS 또는 FAIL:로 시작한다.
                    # 전체 부분검색은 "does not pass"·"통과(pass) 못함" 같은 FAIL 본문에
                    # 걸려 판정을 뒤집으므로, 마지막 줄만 본다.
                    _review = _last_assistant_text(reviewer_msgs).strip()
                    _lines = _review.splitlines()
                    _verdict = _lines[-1].strip().upper() if _lines else ""
                    review_pass = r_status == "done" and _verdict.startswith("PASS")
                    if not review_pass:
                        # 리뷰어가 별도 컨텍스트에서 돌므로 지적이 자동으로 남지 않는다 —
                        # Developer가 보고 고칠 수 있게 명시적으로 넣어 준다.
                        if _review:
                            all_messages.append({
                                "role": "user",
                                "content": "[Reviewer 지적 — 수정하세요]\n" + _review})
                        status = await _run_developer(plan)
            else:
                # Planner 실패 — 안전 폴백: 계획 없이 올인원 Developer로 처리.
                status = await _run_developer("")
        else:
            # single — 기존 올인원 경로 그대로(변경 없음).
            status = await _run_developer("")

        if status != "done":
            await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
            return all_messages

        # (제거됨) 변경 0건일 때 이어붙이던 continue_nudge — Ox의 게으른 read 루프를 겨냥한
        # 레거시 크러치였다. 질문·의견·이미 완료된 요청에도 재실행돼 돈을 낭비하고(실측),
        # 2차 넛지는 불필요한 편집까지 강요했다. 이제 "말로 완료"는 Acceptance Gate가 증거로
        # 판정하므로 맹목적 넛지는 불필요하다.
        if status != "done":
            await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
            return all_messages

        # 변경 0건 — build/test가 통과해도 그건 이번 run이 검증된 게 아니라 아무것도 안 한 것이다.
        # "작업 완료 — 검증 통과"로 보고하면 모델이 하겠다고만 하고 끝낸 run이 성공으로 둔갑한다.
        if not state["files_changed"]:
            await finish("completed_unverified",
                         "코드 변경 없이 종료했습니다(검증 대상 없음). 수정이 필요한 요청이었다면 다시 지시해 주세요.")
            return all_messages

        # ── Gate coverage 복구 — gate 0인 코드 변경 run은 완전 검증 완료가 될 수 없다 ──
        # 실측(프로브 3/3)에서 모델은 update_tasks는 부르고 update_gates만 건너뛰었다.
        # 전체 Developer 루프를 다시 돌리지 않는다 — gate만 쓰는 짧은 턴 1회(step 3, flash).
        if needs_gate_recovery(route_kind, state["files_changed"],
                               len(await store.list_gates(session_id)) if session_id else 0):
            state["gate_recovery_ran"] = True
            try:
                await send("gate_recovery", {"phase": "start"})
                await self._run_role(
                    "gate_recovery", build_gate_recovery_context(
                        goal, state["files_changed"], await store.list_tasks(session_id)),
                    send, session_id, ws, state, recent_calls, step_base, room_memory,
                    tools=GATE_RECOVERY_TOOL_SCHEMAS, requirements=req_block, persist=False,
                )
            except Exception as err:
                # 복구 실패가 run을 깨뜨리면 안 된다 — gate 없이 정직하게 마감하면 된다.
                error_log.record("gate_recovery", str(err), session_id)
            step_base += GATE_RECOVERY_MAX_STEPS
            _recovered = bool(session_id and await store.list_gates(session_id))
            await send("gate_recovery", {"phase": "done",
                                         "result": "recovered_gated" if _recovered
                                         else "generic_only"})

        # ── Strict 검증 게이트 — 신뢰성은 모델이 아니라 프로세스가 보장한다 ──
        # 완료 = 검증(test/build) 통과 + 요구사항 게이트 통과. 모델이 "됐습니다" 해도
        # 프로세스가 실제로 돌려 통과해야 완료로 인정한다. 실패하면 1회 수리 재시도,
        # 그래도 실패면 verification_failed로 정직하게 보고하고 커밋하지 않는다.
        # 흐름: implementation → generic verification → acceptance gate verification
        #       → integration verification → completed
        await self._mark_testing(session_id, send)  # 칸반: 검증(test) 단계 진입(프로세스 소유)
        await self._check_change_risks(ws, send, state["files_changed"])  # F6/F7: 위험 변경 감지(비차단, autocommit 전)
        vstate, report = await self._verify(ws, send)
        # failed일 때만 1회 수리 재시도(bounded — 무제한 repair loop 금지, 비용 상한).
        if vstate == "failed":
            await send("verify_failed", {"report": report[:800]})
            all_messages.append({"role": "user", "content":
                "[검증 실패 — 프로세스가 test/build를 실제로 돌린 결과다. 아래를 고쳐 통과시켜라]\n" + report})
            status = await _run_developer("")
            if status == "done":
                vstate, report = await self._verify(ws, send)
        if vstate == "failed":
            await finish("verification_failed",
                         "검증(test/build) 실패로 완료하지 못했습니다. 커밋하지 않았습니다:\n" + report[:600])
            return all_messages

        # ── Acceptance Gate 검증 — build/test 통과 ≠ 요구사항 충족 ──
        gstate, greport = await self._verify_gates(ws, session_id, send)
        if gstate == "failed":
            await send("verify_failed", {"report": greport[:800]})
            all_messages.append({"role": "user", "content":
                "[요구사항 게이트 검증 실패 — 프로세스가 각 gate의 명령을 실제로 실행한 결과다. "
                "해당 요구사항을 고쳐 통과시켜라]\n" + greport})
            status = await _run_developer("")
            if status == "done":
                await self._mark_testing(session_id, send)
                vstate, report = await self._verify(ws, send)
                gstate, greport = await self._verify_gates(ws, session_id, send)
        if vstate == "failed":
            await finish("verification_failed",
                         "검증(test/build) 실패로 완료하지 못했습니다. 커밋하지 않았습니다:\n" + report[:600])
            return all_messages
        if gstate == "failed":
            await finish("verification_failed",
                         "요구사항 게이트 검증 실패로 완료하지 못했습니다. 커밋하지 않았습니다:\n" + greport[:600])
            return all_messages

        # ── Integration 검증 — 합쳐진 최종 상태의 회귀·게이트 일관성 ──
        istate, ireport = await self._verify_integration(ws, session_id, send)
        if istate == "failed":
            await finish("verification_failed",
                         "통합 검증 실패로 완료하지 못했습니다. 커밋하지 않았습니다:\n" + ireport[:600])
            return all_messages

        # 완료 정책 — gate 없는 코드 변경은 completed가 되지 않는다(핵심 invariant).
        # Task IR requirement가 passed gate로 이어지지 않으면 completed로 두지 않는다
        # (traceability를 관측 지표에서 완료 판정으로 승격 — 차단이 아니라 강등).
        # Task IR off(=reqs 없음)면 gap=False라 기존 동작 그대로다.
        _reqs = self._task_ir_reqs.get(session_id) if session_id else None
        _trace = (traceability.compute_traceability(_reqs, await store.list_gates(session_id))
                  if _reqs else None)
        final = resolve_completion_verification(
            gstate, vstate, bool(_trace and _trace["false_completion_candidate"]))
        if gstate == "none" and vstate != "passed":
            await send("verify_unavailable", {"report": report[:400]})
        summary = await self._completion_summary(
            session_id, final, gstate, vstate, istate, len(state["files_changed"]),
            _untraced_requirements(_reqs, _trace))
        await finish(final, summary=summary)
        return all_messages

    async def _completion_summary(self, session_id: str, status: str, gstate: str,
                                  vstate: str, istate: str, n_files: int,
                                  untraced: list | None = None) -> dict:
        """최종 보고의 재료를 process-owned 사실만으로 모은다(모델 self-report 아님).

        모델이 "모두 완료했습니다"라고 썼는지는 근거로 쓰지 않는다. 여기 담기는 것은
        프로세스가 직접 실행해 얻은 결과뿐이다 — gate 실행 결과, test/build 결과,
        integration 결과, 그리고 (finish에서 채워지는) 실제 commit/push 결과.
        commit/push는 아직 실행되지 않았으므로 None으로 두고 finish가 채운다.
        """
        gates = await store.list_gates(session_id) if session_id else []
        by = {"passed": [], "failed": [], "other": []}
        for g in gates:
            st = g.get("status", "pending")
            key = st if st in ("passed", "failed") else "other"
            by[key].append({"title": g.get("title", ""), "status": st,
                            "reason": g.get("failure_reason") or "",
                            "evidence": str(g.get("evidence") or "")[:300]})
        return {
            "status": status,
            "verified_requirements": by["passed"],
            "unverified_requirements": by["other"],
            "failed_requirements": by["failed"],
            "generic_verification": vstate,
            "integration_verification": istate,
            "gate_state": gstate,
            "files_changed_count": n_files,
            # gate로 이어지지 않은 Task IR 요구사항(무엇이 미검증인지 — 강등 사유의 구체값).
            "untraced_requirements": untraced or [],
            "commit_status": None,   # finish가 실제 결과로 채운다
            "push_status": None,
            # 완전 검증이 아니라면 그 이유를 기계가 읽을 수 있게 남긴다(UI·telemetry).
            "blocking_reason": _blocking_reason(status, gstate, vstate),
        }

    @staticmethod
    def format_completion_summary(s: dict) -> str:
        """CompletionSummary → 사용자에게 보여줄 짧은 보고(deterministic — LLM 재호출 없음).

        보여주는 것: 무엇을 검증했는지 / 미검증·실패 / commit·push 상태.
        보여주지 않는 것: 모델 이름·tool call 수·token·compaction·retry·추론(Debug에서 본다).
        """
        verified = s.get("verified_requirements") or []
        unverified = s.get("unverified_requirements") or []
        failed = s.get("failed_requirements") or []
        gstate = s.get("gate_state")
        vstate = s.get("generic_verification")

        # 헤더 앞뒤로 빈 줄 — 앞선 진행 설명과 최종 보고를 떼어 놓고, 결론과 근거 목록도
        # 붙어 읽히지 않게 한다(모바일에서 한 덩어리로 뭉쳐 보였다).
        lines = ["", "완료했습니다." if s.get("status") == "completed"
                 else "작업은 완료했습니다. 다만 일부 항목은 검증하지 못했습니다.", ""]
        for r in verified:
            lines.append(f"✓ {r['title']}")
        for r in failed:
            lines.append(f"✗ {r['title']}" + (f" — {r['reason']}" if r.get("reason") else ""))
        for r in unverified:
            label = {"unavailable": "검증 방법 없음", "blocked": "차단",
                     "abandoned": "포기"}.get(r.get("status"), "미검증")
            lines.append(f"! {r['title']} — {r.get('reason') or label}")

        for r in s.get("untraced_requirements") or []:
            lines.append(f"! {r.get('text') or r.get('id')} — 검증한 gate가 없습니다(미검증)")

        if vstate == "passed":
            lines.append("✓ 기존 테스트·빌드 통과")
            # "최종 회귀 확인"은 integration이 실제로 회귀 검사를 돌렸을 때만 참이다.
            # generic이 unavailable이면 integration도 회귀를 확인한 게 아니라 gate 실패가
            # 없었을 뿐이다 — 그때 이 줄을 찍으면 "회귀 미확인"과 정면으로 모순된다(실측).
            if s.get("integration_verification") == "passed":
                lines.append("✓ 최종 회귀 확인")
        elif vstate == "unavailable":
            lines.append("! 실행 가능한 test/build 없음 — 회귀 미확인")
        # gate가 없었다는 사실을 침묵하지 않는다 — 침묵하면 완전 검증으로 읽힌다.
        if gstate == "none":
            lines.append("! 요구사항 게이트 없음 — 요청 충족 여부는 검증되지 않았습니다")

        commit, push = s.get("commit_status"), s.get("push_status")
        n = s.get("files_changed_count") or 0
        if not n:
            lines.append("– 코드 변경 없음")
        elif commit is None:
            lines.append(f"– 변경 {n}개 파일")
        elif not commit:
            lines.append(f"✗ 변경 {n}개 파일 · 자동 commit 안 됨 — 수동 확인 필요")
        elif push:
            lines.append(f"✓ 변경 {n}개 파일 · commit·push 완료")
        elif s.get("status") == "completed":
            lines.append(f"! 변경 {n}개 파일 · 로컬 commit · push 실패 — 수동 push 필요")
        else:
            lines.append(f"– 변경 {n}개 파일 · 로컬 commit (미검증이라 push 안 함)")
        return "\n".join(lines)

    @staticmethod
    def _finish_message(status: str) -> str:
        if status == "cancelled":
            return "사용자가 중단했습니다."
        if status == "context_blocked":
            return f"컨텍스트 한도({int(CONTEXT_BLOCK_RATIO * 100)}%)에 도달해 중단했습니다. 새 세션에서 계속 진행하세요."
        if status == "budget_exceeded":
            return "작업 비용이 예산 상한에 도달해 중단했습니다. 예산을 올리거나 새 세션에서 계속하세요."
        if status == "repeated":
            return "동일한 도구 호출이 반복되어 중단했습니다."
        return "최대 실행 단계를 초과했습니다."
