import json
from typing import AsyncIterator, Any

import httpx


class DeepSeekAdapter:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.base = "https://api.deepseek.com"

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: bool = False,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if thinking:
            payload["extra_body"] = {"thinking": {"type": "enabled"}}

        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30)) as client:
            async with client.stream(
                "POST",
                f"{self.base}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"DeepSeek API 오류 {resp.status_code}: {body.decode(errors='replace')[:500]}"
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta:
                        yield delta
