import asyncio
import base64
import hashlib
import json
import mimetypes
import re
import subprocess
import time
import uuid

import httpx
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import settings
from .. import errors as error_log
from ..db import store
from ..llm.factory import create_adapter
from ..orchestrator.model_router import ModelRouter
from ..tools.registry import APPROVAL_REQUIRED, CHAT_TOOLS, TOOL_SCHEMAS, execute_tool
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30
MAX_REPEATED_CALLS = 3
CONTEXT_BLOCK_RATIO = 0.95
# 이 비율을 넘으면 오래된 대화를 요약해 모델 컨텍스트를 압축한다(비파괴 — 표시/저장용 원본은 유지).
CONTEXT_COMPACT_RATIO = 0.75
COMPACT_KEEP_RECENT = 8
# 부수효과·승인이 없는 읽기 전용 도구 — 한 응답에 여러 개면 병렬 실행 가능
READ_ONLY_TOOLS = {"read_file", "list_dir", "grep"}
# Reviewer↔Debugger 자기수정 루프의 최대 검증 사이클.
# ModelRouter의 debugger Pro 승격 임계(retry_count>=3)와 맞물려,
# 마지막(3번째) Debugger 시도가 Pro로 승격된다.
MAX_REVIEW_CYCLES = 3

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

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "agents"
GLOBAL_MEMORY_PATH = Path(__file__).resolve().parent.parent.parent / "GLOBAL_MEMORY.md"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


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
- 응답은 한국어로 한다.
- 응답에 이모지와 이미지를 넣지 않는다.
- 가독성을 위해 줄바꿈과 문단을 적극적으로 쓴다. 긴 문장을 한 덩어리로 붙이지 말고, 요점마다 줄을 나누고 관련된 내용은 문단으로 묶는다.
- 코드를 추측하지 말고 파일을 읽어 확인한다.
- 목표에 필요한 최소한의 파일만 읽는다. 전수 탐색하지 말고, 충분히 파악되면 즉시 다음 단계로 넘어간다.
- 도구 호출 전에 진행 상황을 짧은 텍스트로 설명한다.
- 같은 도구를 같은 인자로 반복 호출하지 않는다.

## 환경
- 워크스페이스: 로컬 마운트 디렉터리
- 도구: read_file, list_dir, grep, write_file, edit_file, bash, ask_user, update_tasks, save_skill
- write_file/edit_file/bash/save_skill는 사용자 승인이 필요하다.
- 축적된 Skill이 있으면 관련 작업에서 우선 활용한다. 여러 단계로 성공했고 앞으로 반복될 절차라면 save_skill로 저장해 다음에 재사용한다."""


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
    관련 skill이 없으면 빈 문자열(아무것도 삽입하지 않음)."""
    sdir = Path(workspace) / ".forge" / "skills"
    if not sdir.is_dir():
        return ""
    terms = set(_skill_terms(query))
    if not terms:
        return ""
    scored: list[tuple[int, str, str]] = []
    for p in sorted(sdir.glob("*.md")):
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            continue
        stem_l = p.stem.lower()
        body_l = body.lower()
        score = sum(3 for t in terms if t in stem_l) + sum(1 for t in terms if t in body_l)
        if score > 0:
            scored.append((score, p.stem, body))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], x[1]))
    blocks: list[str] = []
    used = 0
    for _score, stem, body in scored[:MAX_ACTIVE_SKILLS]:
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


def _system_for(role: str, room_memory: str = "", skills: str = "") -> str:
    # 안정 프리픽스(BASE+role)를 먼저, 동적 tail(memory→skills)을 뒤에 둔다.
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
    return "".join(parts)


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
        # reasoning_content 400을 한 번 겪은 세션 — 이후 호출은 미리 reasoning을 벗긴다.
        self._strip_reasoning_sessions: set[str] = set()
        self._auto_approve_sessions: set[str] = set()
        # 세션별 컨텍스트 압축 상태: {session_id: {"summary": str, "covered": int}}
        # summary가 all_messages[:covered]를 대체(모델 전송 시에만).
        self._compaction: dict[str, dict] = {}

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
            async for delta in self._adapter_for(self.router.triage_model).stream_chat(messages):
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

    def resolve_pending_approvals(self, session_id: str = "") -> int:
        """대기 중인 승인 요청을 모두 승인 처리한다(자동 승인 켤 때)."""
        count = 0
        for approval_id, fut in list(self.pending_approvals.items()):
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
        await send(
            "approval_request",
            {"id": approval_id, "tool": name, "args": args},
        )
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending_approvals[approval_id] = fut
        try:
            return await fut
        finally:
            self.pending_approvals.pop(approval_id, None)

    async def _ask_user(
        self, args: dict, send: Callable[[str, dict], Awaitable[None]]
    ) -> str:
        question_id = uuid.uuid4().hex
        await send(
            "question_request",
            {
                "id": question_id,
                "question": args.get("question", ""),
                "options": args.get("options", []),
            },
        )
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending_questions[question_id] = fut
        try:
            return await fut
        finally:
            self.pending_questions.pop(question_id, None)

    async def _triage(self, all_messages: list[dict]) -> tuple[str, str, int, int]:
        """마지막 요청이 코드 작업인지(agent) 일반 대화·질문인지(chat) 분류한다.

        chat이면 전체 파이프라인을 건너뛰고 단일 패스로 답한다.
        """
        # 최근 대화만 압축해서 분류 입력으로 쓴다 (텍스트만).
        lines: list[str] = []
        for m in all_messages[-6:]:
            role = m.get("role", "")
            if role == "tool":
                continue
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                ) or "[이미지]"
            text = str(content).strip()
            if text:
                lines.append(f"{role}: {text[:500]}")
        transcript = "\n".join(lines)

        messages = [
            {
                "role": "system",
                "content": (
                    "너는 요청 분류기다. 마지막 사용자 메시지가 로컬 코드베이스를 "
                    "수정·생성·실행·리팩터링·디버깅하는 작업이면 AGENT, 그 외 일반 대화·"
                    "질문·설명·조회면 CHAT 이다. 코드를 읽어 설명만 하면 CHAT, 파일을 "
                    "고치거나 명령을 실행해야 하면 AGENT.\n"
                    "AGENT면 난이도도 판정한다: 여러 파일·여러 단계·설계 변경·까다로운 디버깅이 "
                    "필요하면 COMPLEX, 단순한 한두 단계 수정이면 SIMPLE.\n"
                    "형식: 'CHAT' 또는 'AGENT SIMPLE' 또는 'AGENT COMPLEX' — 이 중 하나만 답한다."
                ),
            },
            {"role": "user", "content": transcript},
        ]

        parts: list[str] = []
        prompt_t = 0
        completion_t = 0
        async for delta in self._adapter_for(self.router.triage_model).stream_chat(messages):
            if delta.get("content"):
                parts.append(delta["content"])
            if delta.get("usage"):
                prompt_t += delta["usage"].get("prompt_tokens", 0)
                completion_t += delta["usage"].get("completion_tokens", 0)
        answer = "".join(parts).upper()
        route = "agent" if "AGENT" in answer else "chat"
        complexity = "high" if "COMPLEX" in answer else "normal"
        return route, complexity, prompt_t, completion_t

    async def _run_vision(
        self,
        user_msg: dict,
        send: Callable[[str, dict], Awaitable[None]],
        session_id: str,
    ) -> str:
        route = self.router.select_model("vision")
        await send("role_start", {"role": "vision", "model": route["model"]})

        content = user_msg.get("content", "")
        if isinstance(content, list):
            content = [_to_data_uri_item(c) for c in content]

        messages = [
            {
                "role": "system",
                "content": (
                    "당신은 FORGE Vision 에이전트입니다. 제공된 이미지를 분석하고, "
                    "레이아웃·정렬·간격·색상 대비·다크모드·반응형·오류 화면 등 발견한 사항을 "
                    "한국어로 상세히 설명합니다. 이모지와 이미지는 사용하지 않습니다."
                ),
            },
            {"role": "user", "content": content},
        ]

        parts: list[str] = []
        total_prompt = 0
        total_completion = 0
        async for delta in self._adapter_for(route["model"]).stream_chat(messages):
            if delta.get("content"):
                parts.append(delta["content"])
                await send("text_delta", {"content": delta["content"]})
            if delta.get("usage"):
                total_prompt += delta["usage"].get("prompt_tokens", 0)
                total_completion += delta["usage"].get("completion_tokens", 0)

        analysis = "".join(parts)
        if session_id:
            await store.save_agent_run(
                session_id,
                "vision",
                route["model"],
                total_prompt,
                total_completion,
                route.get("thinking", False),
                route.get("reasoning_effort", ""),
            )
            await store.save_vision_analysis(session_id, "", analysis)
        return analysis

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
    ) -> tuple:
        route = self.router.select_model(role, retry_count, complexity)
        tool_schemas = tools if tools is not None else TOOL_SCHEMAS
        await send("role_start", {
            "role": role, "model": route["model"], "thinking": route["thinking"],
            "prefix_hash": _stable_prefix_hash(role),
        })
        system_msg = {"role": "system", "content": _system_for(role, room_memory, skills)}

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

        for step in range(step_base, step_base + MAX_STEPS):
            if session_id in self._cancel_sessions:
                return "cancelled", total_prompt, total_completion, route

            # 실행 중 사용자가 큐잉한 메시지를 다음 스텝 컨텍스트에 주입
            injected = self._injections.pop(session_id, None) if session_id else None
            if injected:
                for text in injected:
                    user_msg = {"role": "user", "content": "[작업 중 사용자 메시지]\n" + text}
                    all_messages.append(user_msg)
                    await send("user_injected", {"content": text})

            reasoning: list[str] = []
            content: list[str] = []
            reasoning_buf: list[str] = []
            content_buf: list[str] = []
            tool_acc: dict[int, dict[str, Any]] = {}
            usage: dict[str, int] = {}
            last_emit = 0.0

            call_messages = [system_msg, *self._project(all_messages, session_id)]
            if session_id in self._strip_reasoning_sessions:
                call_messages = self._strip_reasoning(call_messages)
            route["model_calls"] += 1
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
                    answer = await self._ask_user(args, send)
                    result = answer if answer else "(응답 없음)"
                    await send("tool_result", {"name": name, "result": result})
                    all_messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    continue

                if name == "update_tasks":
                    tasks = args.get("tasks", [])
                    if session_id:
                        await store.replace_tasks(session_id, tasks)
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

    async def run(
        self,
        history: list[dict],
        emit: EventSink,
        session_id: str = "",
        workspace: str | None = None,
    ) -> list[dict]:
        ws = workspace or settings.workspace
        seq = 0

        async def send(event_type: str, data: dict[str, Any]) -> None:
            nonlocal seq
            seq += 1
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

        # 이미지가 포함된 요청이면 Vision 에이전트로 먼저 분석
        last_user = history[-1] if history and history[-1].get("role") == "user" else None
        if last_user and _has_image(last_user):
            analysis = await self._run_vision(last_user, send, session_id)
            all_messages.append({"role": "user", "content": "[이미지 분석 결과]\n" + analysis})

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
            # done 이벤트를 보내면서 세션 final_status를 영속화(성공 정의·집계 기준).
            if session_id:
                await store.set_session_final_status(session_id, status)
            data = {"status": status}
            if content:
                data["content"] = content
            await send("done", data)

        # 0. Triage — 코드 작업 여부 + 복잡도(planner 모델 승격 판단)
        triage_route, complexity, tp, tc = await self._triage(all_messages)
        await record("triage", tp, tc, {"model": self.router.triage_model, "model_calls": 1})
        if triage_route == "chat":
            status, p, c, route = await self._run_role(
                "chat", all_messages, send, session_id, ws, state, recent_calls,
                step_base, room_memory, tools=CHAT_TOOLS, skills=skills,
            )
            await record("chat", p, c, route)
            if status != "done":
                await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
            else:
                await finish("completed")
            return all_messages

        # 1. Planner — flash 기본, 복잡한 작업이면 pro 승격
        status, p, c, route = await self._run_role(
            "planner", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory,
            skills=skills, complexity=complexity,
        )
        await record("planner", p, c, route)
        step_base += MAX_STEPS
        if status != "done":
            await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
            return all_messages

        # 2. Coder
        status, p, c, route = await self._run_role(
            "coder", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory, skills=skills
        )
        await record("coder", p, c, route)
        step_base += MAX_STEPS
        if status != "done":
            await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
            return all_messages

        # 3. Reviewer ↔ Debugger 자기수정 루프 (상태 기반 반복)
        #    Reviewer가 task를 done/debug로, Debugger가 review로 되돌린다.
        #    모든 task가 done이 될 때까지, 최대 MAX_REVIEW_CYCLES회 반복.
        review_cycle = 0
        debug_attempts = 0
        tasks: list[dict] = []
        final_status = "completed"
        while True:
            status, p, c, route = await self._run_role(
                "reviewer", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory, skills=skills
            )
            await record("reviewer", p, c, route)
            step_base += MAX_STEPS
            if status != "done":
                await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
                return all_messages

            tasks = await store.list_tasks(session_id) if session_id else []
            unfinished = [t for t in tasks if t.get("status") != "done"]
            if not unfinished:
                final_status = "completed"
                break

            review_cycle += 1
            if review_cycle > MAX_REVIEW_CYCLES:
                final_status = "review_limit"
                break

            # debug task가 있으면 Debugger로 수정 후 재검토(review 상태로 되돌림).
            if any(t.get("status") == "debug" for t in tasks):
                debug_attempts += 1
                # retry_count가 임계(3)에 도달하면 마지막 시도가 Pro로 승격된다.
                status, p, c, route = await self._run_role(
                    "debugger", all_messages, send, session_id, ws, state,
                    recent_calls, step_base, room_memory, retry_count=debug_attempts, skills=skills,
                )
                await record("debugger", p, c, route)
                step_base += MAX_STEPS
                if status != "done":
                    await finish(_STATUS_CODES.get(status, "failed"), self._finish_message(status))
                    return all_messages
            # debug는 없지만 아직 done이 아니면(review 등) 루프 재진입 → Reviewer 재실행

        if final_status == "review_limit":
            await finish("review_limit", self._review_limit_message(tasks, state, debug_attempts))
        else:
            await finish("completed", "모든 작업을 완료했습니다.")
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

    @staticmethod
    def _review_limit_message(tasks: list[dict], state: dict, attempts: int) -> str:
        lines = [f"자동 수정 한도({MAX_REVIEW_CYCLES}회)에 도달해 종료했습니다."]
        unfinished = [t for t in (tasks or []) if t.get("status") != "done"]
        if unfinished:
            lines.append("남은 문제:")
            for t in unfinished:
                lines.append(f"- {t.get('title', '')} ({t.get('status', '')})")
        errors = (state or {}).get("errors") or []
        if errors:
            lines.append("관찰된 오류:")
            for e in errors[-5:]:
                lines.append(f"- {e}")
        lines.append(f"자동 수정 시도: {attempts}회")
        lines.append("새 세션에서 남은 문제를 직접 확인하거나 더 구체적인 지시를 주세요.")
        return "\n".join(lines)
