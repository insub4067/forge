from typing import Any, Awaitable, Callable

from ..config import settings
from ..llm.deepseek import DeepSeekAdapter
from ..tools.registry import TOOL_SCHEMAS, execute_tool
from ..sandbox.executor import DockerSandbox

MAX_STEPS = 30

EventSink = Callable[[dict[str, Any]], Awaitable[None]]

SYSTEM_PROMPT = """당신은 FORGE 에이전틱 코딩 에이전트입니다. 로컬 코드베이스에서 자율적으로 작업을 수행합니다.

## 작업 방식
1. 요청을 분석하고 간단한 계획을 세운다.
2. 필요한 도구(read_file, list_dir, grep)를 호출해 코드베이스를 탐색하고 분석한다.
3. 관찰한 결과를 바탕으로 필요한 만큼 반복한다.
4. 완료하면 무엇을 했는지 간결하게 보고한다.

## 원칙
- 코드를 추측하지 말고 반드시 파일을 읽어 확인한다.
- 변경은 요청과 관련된 최소한으로 한다.
- 응답은 한국어로 한다.
- 도구 호출 전에 진행 상황을 짧은 텍스트로 설명한다.

## 환경
- 워크스페이스: 로컬 마운트 디렉터리
- 도구: read_file, list_dir, grep"""


class AgentRuntime:
    def __init__(self):
        self.adapter = DeepSeekAdapter(settings.deep_seek_api_key, settings.deep_seek_model)
        self.sandbox = DockerSandbox()

    async def run(self, history: list[dict], emit: EventSink) -> list[dict]:
        seq = 0

        async def send(event_type: str, data: dict[str, Any]) -> None:
            nonlocal seq
            seq += 1
            await emit({"seq": seq, "type": event_type, "data": data})

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

        for step in range(MAX_STEPS):
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
                name = tc["function"]["name"]
                try:
                    args = __import__("json").loads(tc["function"]["arguments"] or "{}")
                except Exception:
                    args = {}
                await send("tool_call", {"name": name, "args": args})

                try:
                    result = await execute_tool(name, args, settings.workspace)
                except Exception as err:
                    result = f"오류: {err}"
                await send("tool_result", {"name": name, "result": result[:20_000]})

                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result[:20_000]}
                )
        else:
            await send("done", {"content": "최대 실행 단계를 초과했습니다."})

        return messages[1:]  # system 제외하고 반환
