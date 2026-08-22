import asyncio
import base64
import json
import mimetypes
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import settings
from ..db import store
from ..llm.factory import create_adapter
from ..orchestrator.model_router import ModelRouter
from ..tools.registry import APPROVAL_REQUIRED, CHAT_TOOLS, TOOL_SCHEMAS, execute_tool
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30
MAX_REPEATED_CALLS = 3
CONTEXT_BLOCK_RATIO = 0.95

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
- 코드를 추측하지 말고 파일을 읽어 확인한다.
- 도구 호출 전에 진행 상황을 짧은 텍스트로 설명한다.
- 같은 도구를 같은 인자로 반복 호출하지 않는다.

## 환경
- 워크스페이스: 로컬 마운트 디렉터리
- 도구: read_file, list_dir, grep, write_file, edit_file, bash, ask_user, update_tasks
- write_file/edit_file/bash는 사용자 승인이 필요하다."""


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


def _system_for(role: str, room_memory: str = "") -> str:
    parts = [BASE_PROMPT]
    global_mem = _load_global_memory()
    if global_mem:
        parts.append("\n\n## 전역 메모리 (GLOBAL_MEMORY.md)\n" + global_mem)
    if room_memory:
        parts.append("\n\n## 방 메모리 (ROOM_MEMORY.md)\n" + room_memory)
    parts.append("\n\n" + _load_role(role))
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

    def _adapter_for(self, model: str):
        if model not in self._adapters:
            self._adapters[model] = create_adapter(model)
        return self._adapters[model]

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

    def cleanup_session(self, session_id: str) -> None:
        self._running_sessions.discard(session_id)
        self._injections.pop(session_id, None)
        self._cancel_sessions.discard(session_id)

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

    async def _request_approval(
        self, name: str, args: dict, send: Callable[[str, dict], Awaitable[None]]
    ) -> str:
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

    async def _triage(self, all_messages: list[dict]) -> tuple[str, int, int]:
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
                    "고치거나 명령을 실행해야 하면 AGENT. 오직 한 단어(CHAT 또는 AGENT)만 답한다."
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
        return route, prompt_t, completion_t

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
    ) -> tuple:
        route = self.router.select_model(role, retry_count)
        tool_schemas = tools if tools is not None else TOOL_SCHEMAS
        await send("role_start", {"role": role, "model": route["model"], "thinking": route["thinking"]})
        system_msg = {"role": "system", "content": _system_for(role, room_memory)}

        # 이전 role(thinking on)이 남긴 reasoning_content는 이후 호출에서
        # DeepSeek이 거부하므로 제거한다. 현재 role의 tool-loop 내부 reasoning은 유지.
        for msg in all_messages:
            msg.pop("reasoning_content", None)

        total_prompt = 0
        total_completion = 0

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

            async for delta in self._adapter_for(route["model"]).stream_chat(
                [system_msg, *all_messages],
                tool_schemas,
                thinking=route["thinking"],
                reasoning_effort=route["reasoning_effort"],
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
                await send(
                    "context_usage",
                    {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "cached_tokens": usage.get("prompt_cache_hit_tokens", 0)
                        + usage.get("prompt_cache_miss_tokens", 0),
                    },
                )
                used = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                if session_id:
                    await store.update_context_usage(session_id, used)
                if used > settings.logical_budget * CONTEXT_BLOCK_RATIO:
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

            all_messages.append(assistant_msg)

            if not tool_calls:
                return "done", total_prompt, total_completion, route

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
                    decision = await self._request_approval(name, args, send)
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
                    {"role": "tool", "tool_call_id": tc["id"], "content": result[:20_000]}
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

        # 이미지가 포함된 요청이면 Vision 에이전트로 먼저 분석
        last_user = history[-1] if history and history[-1].get("role") == "user" else None
        if last_user and _has_image(last_user):
            analysis = await self._run_vision(last_user, send, session_id)
            all_messages.append({"role": "user", "content": "[이미지 분석 결과]\n" + analysis})

        step_base = 0

        async def record(role: str, p: int, c: int, route: dict) -> None:
            if session_id:
                await store.save_agent_run(
                    session_id,
                    role,
                    route.get("model", ""),
                    p,
                    c,
                    route.get("thinking", False),
                    route.get("reasoning_effort", ""),
                )

        # 0. Triage — 코드 작업이 아니면 단일 chat 패스로 답하고 종료
        triage_route, tp, tc = await self._triage(all_messages)
        await record("triage", tp, tc, {"model": self.router.triage_model})
        if triage_route == "chat":
            status, p, c, route = await self._run_role(
                "chat", all_messages, send, session_id, ws, state, recent_calls,
                step_base, room_memory, tools=CHAT_TOOLS,
            )
            await record("chat", p, c, route)
            if status != "done":
                await send("done", {"content": self._finish_message(status)})
            else:
                await send("done", {})
            return all_messages

        # 1. Planner
        status, p, c, route = await self._run_role(
            "planner", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
        )
        await record("planner", p, c, route)
        step_base += MAX_STEPS
        if status != "done":
            await send("done", {"content": self._finish_message(status)})
            return all_messages

        # 2. Coder
        status, p, c, route = await self._run_role(
            "coder", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
        )
        await record("coder", p, c, route)
        step_base += MAX_STEPS
        if status != "done":
            await send("done", {"content": self._finish_message(status)})
            return all_messages

        # 3. Reviewer
        status, p, c, route = await self._run_role(
            "reviewer", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
        )
        await record("reviewer", p, c, route)
        step_base += MAX_STEPS
        if status != "done":
            await send("done", {"content": self._finish_message(status)})
            return all_messages

        # 4. Debugger (reviewer가 debug 상태를 남긴 경우)
        if session_id:
            tasks = await store.list_tasks(session_id)
            if any(t.get("status") == "debug" for t in tasks):
                status, p, c, route = await self._run_role(
                    "debugger", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
                )
                await record("debugger", p, c, route)
                if status != "done":
                    await send("done", {"content": self._finish_message(status)})
                    return all_messages

        await send("done", {"content": "모든 작업을 완료했습니다."})
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
