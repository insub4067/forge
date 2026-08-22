import asyncio
import json
import subprocess
import uuid
from typing import Any, Awaitable, Callable

from ..config import settings
from ..db import store
from ..llm.deepseek import DeepSeekAdapter
from ..tools.registry import APPROVAL_REQUIRED, TOOL_SCHEMAS, execute_tool
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30
MAX_REPEATED_CALLS = 3
CONTEXT_BLOCK_RATIO = 0.95

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

SYSTEM_PROMPT = """당신은 FORGE 에이전틱 코딩 에이전트입니다. 로컬 코드베이스에서 자율적으로 작업을 수행합니다.

## 작업 방식
1. 요청을 분석하고 간단한 계획을 세운다.
2. 필요한 도구를 호출해 코드베이스를 탐색·분석·수정한다.
3. 관찰한 결과를 반성(reflection)하고 다음 행동을 결정한다.
4. 완료하면 무엇을 했는지 간결하게 보고한다.

## 원칙
- 코드를 추측하지 말고 반드시 파일을 읽어 확인한다.
- 변경은 요청과 관련된 최소한으로 한다.
- 응답은 한국어로 한다.
- 도구 호출 전에 진행 상황을 짧은 텍스트로 설명한다.
- 같은 도구를 같은 인자로 반복 호출하지 않는다. 결과가 바뀌지 않으면 다른 접근을 취한다.

## 사용자 확인
- 설계 방향·기술 선택·범위 등 중요한 결정이 필요하면 ask_user 도구로 질문한다.
- 사소한 것은 스스로 판단하고 진행한다.

## 환경
- 워크스페이스: 로컬 마운트 디렉터리
- 도구: read_file, list_dir, grep, write_file, edit_file, bash, ask_user
- write_file/edit_file/bash는 사용자 승인이 필요하다."""


class AgentRuntime:
    def __init__(self):
        self.adapter = DeepSeekAdapter(settings.deep_seek_api_key, settings.deep_seek_model)
        self.sandbox = DockerSandbox()
        self.pending_approvals: dict[str, asyncio.Future] = {}
        self.pending_questions: dict[str, asyncio.Future] = {}
        self._cancel_sessions: set[str] = set()

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
    async def _git_sha() -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", settings.workspace, "rev-parse", "HEAD",
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

    async def run(
        self, history: list[dict], emit: EventSink, session_id: str = ""
    ) -> list[dict]:
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

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

        for step in range(MAX_STEPS):
            if session_id in self._cancel_sessions:
                await send("done", {"content": "사용자가 중단했습니다."})
                break

            reasoning: list[str] = []
            content: list[str] = []
            tool_acc: dict[int, dict[str, Any]] = {}
            usage: dict[str, int] = {}

            async for delta in self.adapter.stream_chat(messages, TOOL_SCHEMAS):
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                    await send("thinking_delta", {"content": delta["reasoning_content"]})
                if delta.get("content"):
                    content.append(delta["content"])
                    await send("text_delta", {"content": delta["content"]})
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

            if usage:
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
                if used > settings.logical_budget * CONTEXT_BLOCK_RATIO:
                    await send(
                        "done",
                        {
                            "content": f"컨텍스트 한도({int(CONTEXT_BLOCK_RATIO * 100)}%)에 도달해 중단했습니다. 새 세션에서 계속 진행하세요."
                        },
                    )
                    break

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

            if not tool_calls:
                await send("done", {"content": "".join(content)})
                break

            for tc in tool_calls:
                if session_id in self._cancel_sessions:
                    await send("done", {"content": "사용자가 중단했습니다."})
                    return messages[1:]

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
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    await send("done", {"content": result})
                    return messages[1:]

                await send("tool_call", {"name": name, "args": args})

                if name == "ask_user":
                    answer = await self._ask_user(args, send)
                    result = answer if answer else "(응답 없음)"
                    await send("tool_result", {"name": name, "result": result})
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": result}
                    )
                    continue

                if name in APPROVAL_REQUIRED:
                    decision = await self._request_approval(name, args, send)
                    if decision != "approve":
                        result = "사용자가 실행을 거부했습니다."
                        await send("tool_result", {"name": name, "result": result})
                        messages.append(
                            {"role": "tool", "tool_call_id": tc["id"], "content": result}
                        )
                        continue
                    await send("approval_granted", {"name": name})

                if name in APPROVAL_REQUIRED and session_id:
                    sha = await self._git_sha()
                    await store.save_checkpoint(session_id, step, sha)

                try:
                    result = await execute_tool(name, args, settings.workspace)
                    if name in ("write_file", "edit_file") and not result.startswith("오류"):
                        state["files_changed"].append(str(args.get("path")))
                except Exception as err:
                    result = f"오류: {err}"
                    state["errors"].append(f"{name}: {err}")

                await send("state_update", state)
                await send("tool_result", {"name": name, "result": result[:20_000]})

                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result[:20_000]}
                )
        else:
            await send("done", {"content": "최대 실행 단계를 초과했습니다."})

        return messages[1:]  # system 제외하고 반환
