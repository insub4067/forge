import json
from typing import Any, AsyncIterator

import httpx

from ..config import settings


class OpenRouterAdapter:
    """OpenRouter(OpenAI 호환) 어댑터. DeepSeek 어댑터와 delta 방출 형태를 동일하게 맞춰
    agent 루프가 변경 없이 동작한다. DeepSeek 전용 필드("thinking")는 보내지 않는다.

    비용 표시는 DeepSeek 단가 기준이라 OpenRouter 모델엔 부정확하다(무료 모델이면 무의미).
    프롬프트 캐싱이 없어 usage에 cache_hit이 없다(런타임은 0으로 처리)."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.base = settings.openrouter_base

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
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
        if not thinking:
            payload["temperature"] = 0.2

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
                        f"OpenRouter API 오류 {resp.status_code}: {body.decode(errors='replace')[:500]}"
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
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    usage = chunk.get("usage")
                    if usage:
                        delta = dict(delta)
                        delta["usage"] = usage
                    if delta:
                        yield delta
