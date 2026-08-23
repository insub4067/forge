import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import time
import uuid

import httpx
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import settings
from .. import errors as error_log
from .. import eventlog
from .. import skills as skills_lib
from ..db import store
from .. import metrics as metrics_calc
from . import refine
from ..llm.factory import create_adapter
from ..orchestrator.model_router import ModelRouter
from ..tools.registry import APPROVAL_REQUIRED, CHAT_TOOLS, TOOL_SCHEMAS, execute_tool
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30
# Developer는 설계+구현+자체검증+수정을 한 루프에서 하므로 step budget을 넉넉히.
# (옛 구조의 planner+coder+reviewer+debugger 여러 호출을 한 컨텍스트로 합친 것)
DEVELOPER_MAX_STEPS = 60
# Planner/Reviewer는 계획·검증 전담이라 step budget이 작아도 충분(비용·지연 억제).
PLANNER_MAX_STEPS = 10
REVIEWER_MAX_STEPS = 12
_ROLE_MAX_STEPS = {"developer": DEVELOPER_MAX_STEPS,
                   "planner": PLANNER_MAX_STEPS,
                   "reviewer": REVIEWER_MAX_STEPS}
# 막혀서 못 풀 때 pro로 승격해 재시도하는 최대 횟수(무한 루프·비용 폭주 방지).
MAX_ESCALATIONS = 2
MAX_REPEATED_CALLS = 3
# 변경 0건으로 끝나려는 코드 run을 이어붙이는 최대 횟수(read 루프·선언만 멈춤 대응).
NUDGE_MAX = 2
CONTEXT_BLOCK_RATIO = 0.95
# 이 비율을 넘으면 오래된 대화를 요약해 모델 컨텍스트를 압축한다(비파괴 — 표시/저장용 원본은 유지).
CONTEXT_COMPACT_RATIO = 0.75
COMPACT_KEEP_RECENT = 8
# 부수효과·승인이 없는 읽기 전용 도구 — 한 응답에 여러 개면 병렬 실행 가능
READ_ONLY_TOOLS = {"read_file", "list_dir", "grep"}
# Planner용 도구 스키마(읽기 전용만) — 구현·실행 도구를 주지 않아 계획만 하게 강제한다.
READ_ONLY_TOOL_SCHEMAS = [
    t for t in TOOL_SCHEMAS if t["function"]["name"] in READ_ONLY_TOOLS
]

# Skill 선택 삽입 한도 — skill이 많아져도 system prompt가 폭증하지 않게 상위 N개만,
# 총 문자 예산 안에서 삽입한다. 관련 skill이 없으면 아무것도 넣지 않는다.
MAX_ACTIVE_SKILLS = 3
SKILL_CHAR_BUDGET = 6000

# 종료 사유 → done 이벤트 status 코드 (SSE 프로토콜 비파괴적 확장)
_STATUS_CODES = {
    "cancelled": "cancelled",
    "context_blocked": "context_blocked",
    "repeated": "repeated_tool_call",
    "max_steps": "max_steps",
}

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

# repo 루트 = agent.py(backend/app/runtime) 기준 parents[3]. docs·GLOBAL_MEMORY는 루트에 있다.
# (예전 parent×3은 backend를 가리켜 role 프롬프트·글로벌 메모리가 로드된 적이 없었다.)
_REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = _REPO_ROOT / "docs" / "agents"
GLOBAL_MEMORY_PATH = _REPO_ROOT / "GLOBAL_MEMORY.md"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"  # backend/app/uploads(정상)


def _has_image(msg: dict) -> bool:
    content = msg.get("content", "")
    if isinstance(content, list):
        return any(isinstance(c, dict) and c.get("type") == "image_url" for c in content)
    return False


def _to_data_uri_item(item: Any) -> Any:
    if isinstance(item, dict) and item.get("type") == "image_url":
        url = item.get("image_url", {}).get("url", "")
        if isinstance(url, str) and url.startswith("/uploads/"):
            name = url.split("/")[-1]
            path = UPLOADS_DIR / name
            if path.exists():
                mime = mimetypes.guess_type(str(path))[0] or "image/png"
                b64 = base64.b64encode(path.read_bytes()).decode()
                return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    return item

BASE_PROMPT = """당신은 FORGE 에이전틱 코딩 에이전트의 일부입니다. 아래 역할 지침을 따르며 로컬 코드베이스에서 작업합니다.

## 공통 원칙
- 응답은 한국어로 한다. **항상 존댓말(합니다·습니다체)로 쓴다.** 반말·음슴체를 쓰지 않는다.
- **짧고 단정한 문장 위주로 핵심만 전한다.** 전보체에 가깝게 — 한 문장 한 정보, 군더더기·수식어·배경 설명 없이. 한 것과 결과만. (예: "calc.py 생성했습니다. 테스트 통과했습니다." / "버그 3곳 수정했습니다.") 존댓말은 유지한다.
- 응답에 이모지와 이미지를 넣지 않는다.
- 긴 내용은 요점마다 줄을 나눠 읽기 쉽게 한다. 다만 길이를 위해 늘리지는 않는다.
- 코드를 추측하지 말고 파일을 읽어 확인한다.
- 목표에 필요한 최소한의 파일만 읽는다. 전수 탐색하지 말고, 충분히 파악되면 즉시 다음 단계로 넘어간다.
- 도구 호출 전에 진행 상황을 짧은 텍스트로 설명한다.
- 같은 도구를 같은 인자로 반복 호출하지 않는다.
- 로직(분기·루프·파서·문자열 매칭·경계값·money/보안 경로)을 만들거나 고치면, 통과 케이스가 아니라 **자기 로직을 깨는 테스트**를 쓴다. 부분매칭 대신 정확 일치, happy-path 대신 뒤집힌 케이스·빈 입력·경계값을 노린다. 자기가 떠올린 경우만 검증하면 자기 맹점을 그대로 물려받는다 — 실패를 유도하는 테스트가 진짜 검증이다.

## 환경
- 워크스페이스: 로컬 마운트 디렉터리
- 도구: read_file, list_dir, grep, write_file, edit_file, bash, ask_user, update_tasks, save_skill
- write_file/edit_file/bash/save_skill는 사용자 승인이 필요하다.
- 축적된 Skill이 있으면 관련 작업에서 우선 활용한다. 여러 단계로 성공했고 앞으로 반복될 절차라면 save_skill로 저장해 다음에 재사용한다.
- save_skill의 scope는 기본 project다. 프로젝트 특화 절차(그 저장소의 규약·빌드·구조)는 project로, 특정 파일명·경로·도메인에 묶이지 않고 여러 코드베이스에서 재사용 가능한 명백히 범용적인 절차만 global로 저장한다. 판단이 애매하면 project. 단순 메모나 일회성 해결은 Skill로 저장하지 않는다."""


def _prune_tool_result(text: str, head: int = 2500, tail: int = 1200) -> str:
    """모델에 보낼 도구 결과를 축약한다(model-free pruning).

    긴 read_file/bash/grep 결과가 매 스텝 컨텍스트에 누적돼 폭증하는 것을 막는다.
    앞·뒤를 보존하고 가운데를 생략하되, 오류/경고 라인은 함께 남긴다.
    UI 표시는 원본을 쓰고, 이 축약본은 모델 컨텍스트(all_messages)에만 쓴다.
    """
    if len(text) <= head + tail + 300:
        return text[:20_000]
    error_lines = [
        ln for ln in text.splitlines()
        if any(k in ln.lower() for k in ("error", "오류", "fail", "warning", "traceback", "exception"))
    ]
    body = text[:head] + f"\n\n... {len(text) - head - tail}자 생략 ...\n\n" + text[-tail:]
    if error_lines:
        body += "\n\n[주요 오류/경고 라인]\n" + "\n".join(error_lines[:20])
    return body


def _load_role(role: str) -> str:
    path = AGENTS_DIR / f"{role}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _load_global_memory() -> str:
    if GLOBAL_MEMORY_PATH.exists():
        return GLOBAL_MEMORY_PATH.read_text(encoding="utf-8")
    return ""


def _load_room_memory(workspace: str) -> str:
    path = Path(workspace) / "ROOM_MEMORY.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _skill_terms(text: str) -> list[str]:
    """매칭용 키워드: 영문/숫자 토큰 + 2자 이상 한글 런. 소문자화."""
    return [t for t in re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", text.lower())]


def _select_skills(workspace: str, query: str) -> str:
    """요청과 관련된 skill만 골라 삽입한다(selective retrieval, vector DB 없음).

    파일을 로컬에서 읽는 건 무료다 — 비용은 '프롬프트에 들어가는 것'뿐이므로,
    모든 skill을 읽어 요청 키워드와의 겹침으로 점수를 매기고 상위 N개만,
    문자 예산 안에서 삽입한다. 제목 일치는 가중치 3, 본문 일치는 1.
    한글 교착어를 흡수하려고 부분 문자열 포함으로 매칭한다.
    curated+learned(global) + project 3계층을 병합해 대상으로 삼는다(같은 이름은
    project 우선). 점수가 같으면 project skill을 먼저 넣는다(명시적 local 우선).
    관련 skill이 없으면 빈 문자열(아무것도 삽입하지 않음)."""
    if settings.skills_off:  # 실험용: skill 주입 전면 비활성(A/B 측정)
        return ""
    terms = set(_skill_terms(query))
    if not terms:
        return ""
    scored: list[tuple[int, int, str, str]] = []  # (score, project우선, name, body)
    for sk in skills_lib.iter_skills(workspace):
        stem, body = sk["name"], sk["content"]
        stem_l = stem.lower()
        body_l = body.lower()
        score = sum(3 for t in terms if t in stem_l) + sum(1 for t in terms if t in body_l)
        if score > 0:
            proj_first = 0 if sk.get("scope") == "project" else 1
            scored.append((score, proj_first, stem, body))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))  # 점수↓ → project 먼저 → 이름
    blocks: list[str] = []
    used = 0
    for _score, _pf, stem, body in scored[:MAX_ACTIVE_SKILLS]:
        block = f"### skill: {stem}\n{body}"
        if used + len(block) > SKILL_CHAR_BUDGET:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _stable_prefix(role: str) -> str:
    """호출마다 변하지 않는 프리픽스: BASE_PROMPT + role 지침.

    prompt cache는 요청 토큰 프리픽스에 걸리므로, 이 부분을 맨 앞에 고정하면
    같은 role의 모든 호출(스텝·태스크·세션 간)이 이 프리픽스를 캐시 히트한다.
    memory/skills 같은 동적 부분은 뒤에 붙인다."""
    return BASE_PROMPT + "\n\n" + _load_role(role)


def _stable_prefix_hash(role: str) -> str:
    return hashlib.sha256(_stable_prefix(role).encode("utf-8")).hexdigest()[:12]


def _system_for(role: str, room_memory: str = "", skills: str = "", plan: str = "") -> str:
    # 안정 프리픽스(BASE+role)를 먼저, 동적 tail(memory→skills→plan)을 뒤에 둔다.
    parts = [_stable_prefix(role)]
    global_mem = _load_global_memory()
    if global_mem:
        parts.append("\n\n## 전역 메모리 (GLOBAL_MEMORY.md)\n" + global_mem)
    if room_memory:
        parts.append("\n\n## 방 메모리 (ROOM_MEMORY.md)\n" + room_memory)
    if skills:
        parts.append(
            "\n\n## 축적된 Skill (재사용 가능한 해결 절차)\n"
            "관련 작업이면 아래 절차를 우선 활용하라.\n" + skills
        )
    if plan:
        parts.append(
            "\n\n## 외부 계획 (Planner가 수립 — 순서와 완료 조건을 따른다)\n" + plan
        )
    return "".join(parts)


def _planner_context(all_messages: list[dict], max_msgs: int = 8) -> list[dict]:
    """Planner에게 주는 축소 컨텍스트 — 전체 재전송 비용을 피하려고 최근 메시지만 준다.
    (과거 planner가 컨텍스트 전체를 재전송해 비용 73%를 차지했던 문제의 재발 방지)

    도구 이력(tool_calls / role:tool)은 제외한다. 이유가 둘이다.
    1) 최근 N개를 그냥 자르면 슬라이스가 orphan `tool` 메시지로 시작해 DeepSeek이 400을
       낸다("tool must follow tool_calls") — 실제로 planner를 죽인 버그. read 루프로 tool
       메시지가 많이 쌓인 세션에서 재현된다.
    2) Planner는 계획만 세우므로 과거 도구 호출·결과가 필요 없다. user 요청과 assistant
       텍스트만으로 충분하다.
    """
    clean: list[dict] = []
    for m in all_messages:
        role = m.get("role")
        if role == "tool":
            continue  # 도구 결과 — planner에 불필요, orphan이면 400 유발
        if role == "assistant" and m.get("tool_calls"):
            # 도구 호출 어시스턴트 — tool_calls를 벗기고 텍스트만(있을 때) 남긴다.
            if m.get("content"):
                clean.append({"role": "assistant", "content": m["content"]})
            continue
        clean.append(m)
    return clean[-max_msgs:]


def _last_assistant_text(messages: list[dict]) -> str:
    """마지막 assistant 텍스트(계획·리뷰 판정 추출용)."""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _format_question(text: str, line_len: int = 56) -> str:
    """질문 텍스트를 문장 단위로 줄바꿈해 팝업 가독성을 높인다.

    모델이 보낸 질문은 보통 한 줄로 길게 온다. 문장 경계(。.!?) 뒤와,
    한 줄이 지나치게 길어지면 그 지점에서 줄바꿈을 넣어 읽기 쉽게 만든다.
    이미 줄바꿈(모델이 구조화)이 있으면 그대로 둔다."""
    if not text:
        return text
    if "\n" in text:
        return text
    import re
    sentences = re.split(r"(?<=[。.!?])\s+", text.strip())
    out: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) > line_len:
            out.append(buf)
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf:
        out.append(buf)
    return "\n".join(out)


# auto 모드의 multi 전환 기준 — 요청 특성이 복잡 작업으로 보이면 Planner가 선행한다.
_COMPLEX_KEYWORDS = (
    "설계", "리팩토링", "리팩터링", "아키텍처", "마이그레이션", "전체",
    "여러 모듈", "다중 모듈", "시스템 전반", "모노레포", "대규모",
)


# 칸반 invariant: 모델은 todo/working만 설정한다. testing→done은 프로세스(검증 게이트·
# _finalize_tasks)가 소유하므로, 모델이 넣은 done/testing/레거시 상태를 강등한다.
_TASK_STATUS_CLAMP = {
    "todo": "todo", "working": "working",
    "planning": "todo", "in_progress": "working", "in-progress": "working",
    "review": "working", "debug": "working",
}


def _clamp_task_status(status: str) -> str:
    """모델이 설정할 수 있는 task 상태를 todo/working으로 제한한다(done/testing은 프로세스만)."""
    return _TASK_STATUS_CLAMP.get(str(status), "working")


def _estimate_complexity(goal: str, all_messages: list[dict]) -> str:
    """simple | complex — 세션의 에이전트 모드가 auto일 때 single/multi를 가른다."""
    text = goal or ""
    if any(k in text for k in _COMPLEX_KEYWORDS):
        return "complex"
    if len(text) > 300:  # 상세한 요구사항 = 다단계 작업 가능성
        return "complex"
    user_msgs = [m for m in all_messages if m.get("role") == "user"]
    if len(user_msgs) >= 5:  # 이미 여러 단계를 밟은 긴 작업
        return "complex"
    return "simple"


class AgentRuntime:
    def __init__(self):
        self.sandbox = DockerSandbox()
        self.router = ModelRouter()
        self._adapters: dict[str, Any] = {}
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self.pending_questions: dict[str, asyncio.Future] = {}
        self._cancel_sessions: set[str] = set()
        self._injections: dict[str, list[str]] = {}
        self._running_sessions: set[str] = set()
        # 세션별 마지막 이벤트 seq — run마다 0부터 시작하면 폴링 since가 깨지므로
        # 세션 단위로 단조 증가시켜 eventlog.tail(since)의 전제를 보장한다.
        self._last_seq: dict[str, int] = {}
        # reasoning_content 400을 한 번 겪은 세션 — 이후 호출은 미리 reasoning을 벗긴다.
        self._strip_reasoning_sessions: set[str] = set()
        self._auto_approve_sessions: set[str] = set()
        # 세션별 모델 티어: auto(flash+막히면 pro) | pro(항상) | flash(승격 없음)
        self._model_tier: dict[str, str] = {}
        # 세션별 에이전트 모드: auto(복잡도 기반 자동) | multi(경량 3역할) | single(올인원)
        self._agent_mode: dict[str, str] = {}
        # 세션별 컨텍스트 압축 상태: {session_id: {"summary": str, "covered": int}}
        # summary가 all_messages[:covered]를 대체(모델 전송 시에만).
        self._compaction: dict[str, dict] = {}
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
        """최근 keep_recent개를 보존하되, 투영본이 orphan tool 메시지나
        결과 없는 tool_calls로 시작하지 않도록 안전한 경계를 찾는다.
        경계는 user 메시지 또는 tool_calls 없는 assistant 앞이어야 한다.
        압축할 수 없으면 0을 반환."""
        split = len(all_messages) - keep_recent
        while split > 1:
            m = all_messages[split]
            role = m.get("role")
            if role == "user" or (role == "assistant" and not m.get("tool_calls")):
                return split
            split -= 1
        return 0

    @staticmethod
    def _should_compact(measured_input: int, budget: int) -> bool:
        """압축 임계 판단(순수). measured_input은 provider 실측 입력 컨텍스트."""
        return measured_input > budget * CONTEXT_COMPACT_RATIO

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

        - reasoning_content 400: reasoning을 벗겨 즉시 재시도(이후 스텝도 학습)
        - 일시적 오류(429/5xx/timeout/connection): 백오프(1·2·4초) 후 최대 3회 재시도
        - terminal(잘못된 요청·인증 등): 전파
        긴 실행이 네트워크 블립이나 일시적 API 장애로 통째로 죽지 않게 한다."""
        stripped = False
        no_think = False
        transient_attempts = 0
        while True:
            msgs = self._strip_reasoning(messages) if stripped else messages
            call_thinking = False if no_think else thinking
            call_effort = None if no_think else effort
            produced = False
            try:
                async for delta in self._adapter_for(model).stream_chat(
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
                # reasoning_content 400: reasoning을 벗기고 thinking을 꺼서 재시도.
                # non-thinking 호출은 reasoning_content 계약 자체가 없어 확실히 회피된다.
                if kind == "reasoning" and not (stripped and no_think):
                    stripped = True
                    no_think = True
                    if session_id:
                        self._strip_reasoning_sessions.add(session_id)
                    if counters is not None:
                        counters["retries"] = counters.get("retries", 0) + 1
                    error_log.record("llm_recovered", f"thinking 끄고 재시도: {err}", session_id)
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

    def cancel(self, session_id: str) -> None:
        self._cancel_sessions.add(session_id)
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
        self._injections.pop(session_id, None)
        self._cancel_sessions.discard(session_id)
        self._compaction.pop(session_id, None)
        self._status.pop(session_id, None)
        for pid, meta in list(self._pending_meta.items()):
            if meta.get("session_id") == session_id:
                self._pending_meta.pop(pid, None)

    @staticmethod
    async def _git_sha(workspace: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", workspace, "rev-parse", "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return out.decode().strip()
        except Exception:
            return ""

    def set_auto_approve(self, session_id: str, enabled: bool) -> None:
        if enabled:
            self._auto_approve_sessions.add(session_id)
        else:
            self._auto_approve_sessions.discard(session_id)

    def set_model_tier(self, session_id: str, tier: str) -> None:
        self._model_tier[session_id] = tier if tier in ("auto", "pro", "flash") else "auto"

    def set_agent_mode(self, session_id: str, mode: str) -> None:
        """에이전트 모드: auto(복잡도 기반 자동 전환) | multi(Planner→Developer→Reviewer) | single(올인원).
        사용자 선택 UI는 제거됐고 항상 FORGE가 판단한다(auto). 하위호환을 위해 메서드는 유지하되
        저장하지 않는다."""
        return

    def get_agent_mode(self, session_id: str) -> str:
        # 항상 auto — FORGE가 작업 복잡도로 single/multi를 자동 판단한다.
        return "auto"

    def resolve_pending_approvals(self, session_id: str = "") -> int:
        """해당 세션의 대기 승인만 승인 처리한다(자동 승인 켤 때).
        session_id로 필터하지 않으면 한 세션의 auto-approve가 다른 세션의 pending까지 승인한다."""
        count = 0
        for approval_id, fut in list(self.pending_approvals.items()):
            if session_id and self._pending_meta.get(approval_id, {}).get("session_id") != session_id:
                continue
            if not fut.done():
                fut.set_result("approve")
                count += 1
        return count

    async def _request_approval(
        self, name: str, args: dict, send: Callable[[str, dict], Awaitable[None]],
        session_id: str = "",
    ) -> str:
        # 자동 승인 모드면 프롬프트 없이 승인
        if session_id in self._auto_approve_sessions:
            await send("approval_auto", {"tool": name})
            return "approve"
        approval_id = uuid.uuid4().hex
        detail = {"id": approval_id, "tool": name, "args": args}
        await send("approval_request", detail)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending_approvals[approval_id] = fut
        self._pending_meta[approval_id] = {"session_id": session_id, "kind": "approval", **detail}
        self._status_update(session_id, waiting_for="approval", pending=detail)
        try:
            try:
                return await asyncio.wait_for(fut, self.PENDING_TIMEOUT)
            except asyncio.TimeoutError:
                # 무응답이면 무한 매달림 대신 안전하게 거부하고 진행한다.
                error_log.record("approval_timeout", f"{name} 승인 {self.PENDING_TIMEOUT}s 무응답 → 거부", session_id)
                return "reject"
        finally:
            self.pending_approvals.pop(approval_id, None)
            self._pending_meta.pop(approval_id, None)
            self._status_update(session_id, waiting_for=None, pending=None)

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
    ) -> tuple:
        route = self.router.select_model(role, retry_count, complexity, escalate=escalate,
                                         has_image=has_image,
                                         tier=self._model_tier.get(session_id, "auto"))
        tool_schemas = tools if tools is not None else TOOL_SCHEMAS
        await send("role_start", {
            "role": role, "model": route["model"], "thinking": route["thinking"],
            "prefix_hash": _stable_prefix_hash(role),
        })
        system_msg = {"role": "system", "content": _system_for(role, room_memory, skills, plan)}

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
            if session_id:
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

            # vision 모델(이미지 작업)이면 원본 이미지를 data URI로 실어 보낸다(/uploads 경로는
            # 모델이 못 읽음). non-vision 모델에는 이미지를 보내지 않는다(모델이 image 미지원 → 400).
            projected = self._project(all_messages, session_id)
            if has_image:
                call_messages = [
                    system_msg,
                    *[
                        {**m, "content": [_to_data_uri_item(c) for c in m["content"]]}
                        if isinstance(m.get("content"), list) else m
                        for m in projected
                    ],
                ]
            else:
                call_messages = [system_msg, *self._strip_images(projected)]
            # reasoning_content 400을 겪은 세션은 이후 내내 reasoning을 벗기고 thinking도 끈다.
            # (thinking을 켜둔 채 보내면 매 콜마다 400→재시도가 반복돼 낭비 — recovery의 성공
            #  상태와 동일하게 처음부터 thinking을 꺼서 그 재시도 사이클을 없앤다.)
            reasoning_disabled = session_id in self._strip_reasoning_sessions
            if reasoning_disabled:
                call_messages = self._strip_reasoning(call_messages)
            route["model_calls"] += 1
            async for delta in self._stream_with_recovery(
                route["model"],
                call_messages,
                tool_schemas,
                False if reasoning_disabled else route["thinking"],
                None if reasoning_disabled else route["reasoning_effort"],
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

                if name in APPROVAL_REQUIRED:
                    decision = await self._request_approval(name, args, send, session_id)
                    if decision != "approve":
                        result = "사용자가 실행을 거부했습니다."
                        await send("tool_result", {"name": name, "result": result})
                        all_messages.append(
                            {"role": "tool", "tool_call_id": tc["id"], "content": result}
                        )
                        continue
                    await send("approval_granted", {"name": name})

                if name in APPROVAL_REQUIRED and session_id:
                    sha = await self._git_sha(ws)
                    await store.save_checkpoint(session_id, step, sha)

                diff = ""
                try:
                    if tc["id"] in prefetched:
                        result, diff = prefetched[tc["id"]]  # 병렬 prefetch된 읽기 결과
                    else:
                        result, diff = await execute_tool(name, args, ws)
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

                all_messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": _prune_tool_result(result)}
                )

        return "max_steps", total_prompt, total_completion, route

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
                          paths: list[str] | None = None) -> None:
        """성공 완료 시 git 워크스페이스면 자동 commit(+push) — 커밋 누락 방지.

        **에이전트가 실제로 바꾼 경로만** stage·commit한다. `git add -A`는 사람이 편집 중이던
        미커밋 변경까지 에이전트 커밋으로 밀어 올려 push해 버린다(실제 사고 2건).
        best-effort: 실패해도 run을 막지 않는다. AUTO_COMMIT=0으로 끈다.
        ponytail: write_file/edit_file로 바꾼 파일만 센다. bash로 고친 파일은 커밋되지 않는다
        (그 편은 놓치는 쪽이 남의 변경을 커밋하는 쪽보다 안전하다).
        """
        if not settings.auto_commit or not ws:
            return
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
            return

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
                return  # git 저장소가 아님
            rc, out = await _g("status", "--porcelain", "--", *rel, timeout=15)
            if rc != 0 or not out.strip():
                return  # 에이전트가 바꾼 파일에 실제 변경 없음
            msg = f"chore: FORGE 자동 커밋 — {(goal or '작업').strip()[:60]}"
            await _g("add", "--", *rel, timeout=30)
            # 경로를 명시해 커밋 — 사람이 stage해 둔 다른 변경이 섞이지 않는다.
            rc, _ = await _g("commit", "-m", msg, "--", *rel, timeout=30)
            committed = rc == 0
            pushed = False
            if committed:
                rc, _ = await _g("push", timeout=90)
                pushed = rc == 0
            await send("autocommit", {"committed": committed, "pushed": pushed, "message": msg})
        except Exception as err:
            error_log.record("autocommit", str(err), "")

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

    async def _verify(self, ws: str, send: EventSink) -> tuple[str, str]:
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

        if not checks:
            return "unavailable", "검증 대상 없음(test/build 미검출 또는 실행 불가)"
        await send("verify_start", {"checks": [c[0] for c in checks]})
        any_passed = False
        for label, args, cwd, kind in checks:
            rc, out = await _sh(args, cwd)
            if kind == "pytest":
                # 0=통과, 1=실제 실패, 그 외(2~5·-1 timeout/error)=unavailable(이 check 건너뜀).
                if rc == 0:
                    any_passed = True
                elif rc == 1:
                    return "failed", f"[{label}] 테스트 실패 (exit 1):\n{out[-1500:]}"
            else:  # build: 0=통과, 양수=실패(빌드/타입 깨짐), -1(실행 불가)=unavailable
                if rc == 0:
                    any_passed = True
                elif isinstance(rc, int) and rc > 0:
                    return "failed", f"[{label}] 빌드 실패 (exit {rc}):\n{out[-1500:]}"
        return ("passed", "검증 통과: " + ", ".join(c[0] for c in checks)) if any_passed \
            else ("unavailable", "검증 실행 불가(모든 check가 unavailable)")

    async def run(
        self,
        history: list[dict],
        emit: EventSink,
        session_id: str = "",
        workspace: str | None = None,
    ) -> list[dict]:
        ws = workspace or settings.workspace
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
        self._injections.pop(session_id, None)
        if session_id:
            self._running_sessions.add(session_id)

        goal = ""
        for m in reversed(history):
            if m.get("role") == "user":
                goal = str(m.get("content", ""))[:200]
                break
        state: dict[str, Any] = {"goal": goal, "files_changed": [], "errors": []}
        recent_calls: list[str] = []
        all_messages: list[dict] = [*history]
        room_memory = _load_room_memory(ws)
        # 요청과 관련된 skill만 선택 삽입(전량 삽입 금지 — skill이 많아질수록 절감).
        skills = _select_skills(ws, goal)
        skill_names = re.findall(r"### skill: (.+)", skills)
        skill_count = len(skill_names)
        skill_csv = ", ".join(skill_names)

        # 이미지가 포함된 요청이면 Developer를 vision 모델로 실행한다(별도 Vision 호출 없이 —
        # Developer가 이미지를 직접 받아 분석·구현). role은 developer로 기록, 모델만 vision.
        has_image = any(_has_image(m) for m in history if m.get("role") == "user")

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
            )

        async def finish(status: str, content: str = "") -> None:
            # 성공 완료 시 하네스가 장부를 마감한다 — 모델이 잊어도 신뢰성 보장:
            # 남은 task done 처리(칸반), 변경 자동 commit+push(커밋 누락 방지).
            # completed(검증됨)와 completed_unverified(검증 대상 없음) 둘 다 커밋 대상.
            # verification_failed는 여기 안 걸려 절대 커밋되지 않는다(invariant).
            # 변경 0건이면 마감할 장부가 없다 — 태스크를 done으로 올리지도, 커밋하지도 않는다
            # (읽기 전용 요청이거나, 모델이 하겠다고만 하고 안 한 경우).
            if status in ("completed", "completed_unverified") and state["files_changed"]:
                await self._finalize_tasks(session_id, send)
                await self._autocommit(ws, goal, send, state["files_changed"])
            # done 이벤트를 보내면서 세션 final_status를 영속화(성공 정의·집계 기준).
            if session_id:
                await store.set_session_final_status(session_id, status)
            # 학습 후보 수집(적용 없음) — done보다 먼저 보내 같은 스트림에 실린다.
            await self._reflect(session_id, ws, status, send)
            data = {"status": status}
            if content:
                data["content"] = content
            await send("done", data)

        # 0. 라우터 — 단순 대화는 최저가 flash chat으로 빼고, 코드 작업만 Developer로.
        route_kind, tp, tc = await self._triage(all_messages)
        await record("triage", tp, tc, {"model": self.router.triage_model, "model_calls": 1})
        if route_kind == "chat":
            status, p, c, route = await self._run_role(
                "chat", all_messages, send, session_id, ws, state, recent_calls,
                step_base, room_memory, tools=CHAT_TOOLS, skills=skills,
            )
            await record("chat", p, c, route)
            await finish("completed" if status == "done"
                         else _STATUS_CODES.get(status, "failed"),
                         "" if status == "done" else self._finish_message(status))
            return all_messages

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
                has_image=has_image, plan=plan,
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
                    has_image=has_image, plan=plan,
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
            )
            await record("planner", p, c, route)
            step_base += PLANNER_MAX_STEPS
            plan = _last_assistant_text(planner_msgs) if p_status == "done" else ""

            if p_status == "done" and plan:
                # 2b. Developer — 계획을 받아 실행(+승격 루프).
                status = await _run_developer(plan)
                if status == "done":
                    # 2c. Reviewer — 독립 검증(flash). 문제 시 Developer가 1회 수정
                    #     (리뷰↔수정 왕복 churn 방지 — 리뷰 루프는 최대 1회).
                    r_status, p, c, route = await self._run_role(
                        "reviewer", all_messages, send, session_id, ws, state, recent_calls,
                        step_base, room_memory, skills=skills,
                    )
                    await record("reviewer", p, c, route)
                    step_base += REVIEWER_MAX_STEPS
                    # reviewer.md 규약: 마지막 줄이 정확히 PASS 또는 FAIL:로 시작한다.
                    # 전체 부분검색은 "does not pass"·"통과(pass) 못함" 같은 FAIL 본문에
                    # 걸려 판정을 뒤집으므로, 마지막 줄만 본다.
                    _lines = _last_assistant_text(all_messages).strip().splitlines()
                    _verdict = _lines[-1].strip().upper() if _lines else ""
                    review_pass = r_status == "done" and _verdict.startswith("PASS")
                    if not review_pass:
                        # 리뷰 피드백(FAIL 내용)이 컨텍스트에 남아 있어 Developer가 그대로 보고 수정.
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

        # ── 이어붙이기 — 선언만 하고 멈추거나 읽기만 반복하는 것을 프로세스가 밀어준다 ──
        # 루프는 tool_call이 없으면 즉시 끝난다. 모델이 "작성합니다"라고만 하고 멈추면 run이
        # 종료돼 사용자가 "끝났어?"라고 물어야 이어지던 문제(실측), 그리고 write 직전까지 가서
        # read만 반복하던 문제(Ox의 read 루프, 실측)를 겨냥한다.
        # 파일 변경 0이 지속되는 동안 최대 NUDGE_MAX회 밀어주되 문구를 점점 강하게 한다.
        # 진전(파일 변경)이 생기면 즉시 루프를 빠져나가고, 상한에 닿으면 정직하게 끝낸다.
        nudge = 0
        while not state["files_changed"] and status == "done" and nudge < NUDGE_MAX:
            nudge += 1
            await send("continue_nudge", {"reason": "no_change", "attempt": nudge})
            if nudge == 1:
                # 1차: 사용자 지시 우선 — "바꾸지 마"라고 한 요청에 편집을 강요하지 않는다.
                msg = ("[프로세스 확인] 아직 파일을 하나도 바꾸지 않았다. "
                       "사용자가 코드 변경을 요청한 경우에만, 설명에서 멈추지 말고 지금 실행해 끝내라. "
                       "조사·설명·확인 요청이거나 사용자가 변경하지 말라고 했다면 아무것도 바꾸지 말고 "
                       "한 줄로만 답하라.")
            else:
                # 2차 이후: 읽기만 반복하는 상황 — 더 읽지 말고 지금 쓰라고 못박는다.
                msg = ("[프로세스 확인] 여전히 파일을 바꾸지 않았다. 더 읽지 말고(read/grep/list 금지) "
                       "지금 write_file 또는 edit_file로 실제 변경을 만들어 끝내라. "
                       "정말로 변경이 필요 없는 요청이면 그 이유만 한 줄로 답하라.")
            all_messages.append({"role": "user", "content": msg})
            status = await _run_developer(plan)
        if status != "done":
            await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
            return all_messages

        # 변경 0건 — build/test가 통과해도 그건 이번 run이 검증된 게 아니라 아무것도 안 한 것이다.
        # "작업 완료 — 검증 통과"로 보고하면 모델이 하겠다고만 하고 끝낸 run이 성공으로 둔갑한다.
        if not state["files_changed"]:
            await finish("completed_unverified",
                         "코드 변경 없이 종료했습니다(검증 대상 없음). 수정이 필요한 요청이었다면 다시 지시해 주세요.")
            return all_messages

        # ── Strict 검증 게이트 — 신뢰성은 모델이 아니라 프로세스가 보장한다 ──
        # 완료 = 검증(test/build) 통과. 모델이 "됐습니다" 해도 프로세스가 실제로 돌려
        # 통과해야 완료로 인정한다. 실패하면 1회 수리 재시도, 그래도 실패면
        # verification_failed로 정직하게 보고하고 커밋하지 않는다(검증 안 된 코드는 안 나간다).
        await self._mark_testing(session_id, send)  # 칸반: 검증(test) 단계 진입(프로세스 소유)
        vstate, report = await self._verify(ws, send)
        # failed일 때만 1회 수리 재시도(bounded — 무제한 repair loop 금지, 비용 상한).
        if vstate == "failed":
            await send("verify_failed", {"report": report[:800]})
            all_messages.append({"role": "user", "content":
                "[검증 실패 — 프로세스가 test/build를 실제로 돌린 결과다. 아래를 고쳐 통과시켜라]\n" + report})
            status = await _run_developer("")
            if status == "done":
                vstate, report = await self._verify(ws, send)
        # 3상태 완료 정책: passed=검증됨 / unavailable=검증불가(정직 표기) / failed=커밋 금지.
        if vstate == "failed":
            await finish("verification_failed",
                         "검증(test/build) 실패로 완료하지 못했습니다. 커밋하지 않았습니다:\n" + report[:600])
        elif vstate == "passed":
            await finish("completed", "작업 완료 — 검증 통과.")
        else:  # unavailable — 검증 못 함을 '검증 성공'으로 기록하지 않는다(별도 상태).
            await send("verify_unavailable", {"report": report[:400]})
            await finish("completed_unverified", "작업 완료(검증 대상 없음 — 미검증). " + report[:200])
        return all_messages

    @staticmethod
    def _finish_message(status: str) -> str:
        if status == "cancelled":
            return "사용자가 중단했습니다."
        if status == "context_blocked":
            return f"컨텍스트 한도({int(CONTEXT_BLOCK_RATIO * 100)}%)에 도달해 중단했습니다. 새 세션에서 계속 진행하세요."
        if status == "repeated":
            return "동일한 도구 호출이 반복되어 중단했습니다."
        return "최대 실행 단계를 초과했습니다."
