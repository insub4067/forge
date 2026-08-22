import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import settings
from ..db import store
from ..llm.factory import create_adapter
from ..tools.registry import APPROVAL_REQUIRED, TOOL_SCHEMAS, execute_tool
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30
MAX_REPEATED_CALLS = 3
CONTEXT_BLOCK_RATIO = 0.95

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "agents"
GLOBAL_MEMORY_PATH = Path(__file__).resolve().parent.parent.parent / "GLOBAL_MEMORY.md"

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


def _role_model(role: str) -> str:
    mapping = {
        "planner": settings.planner_model,
        "coder": settings.coder_model,
        "reviewer": settings.reviewer_model,
        "debugger": settings.debugger_model,
    }
    return mapping.get(role) or settings.deep_seek_model


class AgentRuntime:
    def __init__(self):
        self.sandbox = DockerSandbox()
        self._adapters: dict[str, Any] = {}
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self.pending_questions: dict[str, asyncio.Future] = {}
        self._cancel_sessions: set[str] = set()

    def _adapter_for(self, role: str):
        model = _role_model(role)
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
    ) -> str:
        await send("role_start", {"role": role})
        messages: list[dict] = [
            {"role": "system", "content": _system_for(role, room_memory)},
            *all_messages,
        ]

        total_prompt = 0
        total_completion = 0

        for step in range(step_base, step_base + MAX_STEPS):
            if session_id in self._cancel_sessions:
                return "cancelled", total_prompt, total_completion

            reasoning: list[str] = []
            content: list[str] = []
            reasoning_buf: list[str] = []
            content_buf: list[str] = []
            tool_acc: dict[int, dict[str, Any]] = {}
            usage: dict[str, int] = {}
            last_emit = 0.0

            async for delta in self._adapter_for(role).stream_chat(messages, TOOL_SCHEMAS):
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
                    return "context_blocked", total_prompt, total_completion

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

            messages.append(assistant_msg)
            all_messages.append(assistant_msg)

            if not tool_calls:
                return "done", total_prompt, total_completion

            for tc in tool_calls:
                if session_id in self._cancel_sessions:
                    return "cancelled", total_prompt, total_completion

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
                    return "repeated", total_prompt, total_completion

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

        return "max_steps", total_prompt, total_completion

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

        goal = ""
        for m in reversed(history):
            if m.get("role") == "user":
                goal = str(m.get("content", ""))[:200]
                break
        state: dict[str, Any] = {"goal": goal, "files_changed": [], "errors": []}
        recent_calls: list[str] = []
        all_messages: list[dict] = [*history]
        room_memory = _load_room_memory(ws)

        step_base = 0

        # 1. Planner
        status, p, c = await self._run_role(
            "planner", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
        )
        if session_id:
            await store.save_agent_run(session_id, "planner", _role_model("planner"), p, c)
        step_base += MAX_STEPS
        if status != "done":
            await send("done", {"content": self._finish_message(status)})
            return all_messages

        # 2. Coder
        status, p, c = await self._run_role(
            "coder", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
        )
        if session_id:
            await store.save_agent_run(session_id, "coder", _role_model("coder"), p, c)
        step_base += MAX_STEPS
        if status != "done":
            await send("done", {"content": self._finish_message(status)})
            return all_messages

        # 3. Reviewer
        status, p, c = await self._run_role(
            "reviewer", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
        )
        if session_id:
            await store.save_agent_run(session_id, "reviewer", _role_model("reviewer"), p, c)
        step_base += MAX_STEPS
        if status != "done":
            await send("done", {"content": self._finish_message(status)})
            return all_messages

        # 4. Debugger (reviewer가 debug 상태를 남긴 경우)
        if session_id:
            tasks = await store.list_tasks(session_id)
            if any(t.get("status") == "debug" for t in tasks):
                status, p, c = await self._run_role(
                    "debugger", all_messages, send, session_id, ws, state, recent_calls, step_base, room_memory
                )
                if session_id:
                    await store.save_agent_run(session_id, "debugger", _role_model("debugger"), p, c)
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
