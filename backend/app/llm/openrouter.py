import json
from typing import AsyncIterator, Any

import httpx


class OpenRouterAdapter:
    """OpenRouter(OpenAI 호환) 어댑터 — Ox Alpha 등 stealth 모델 실험용.

    DeepSeekAdapter와 스트리밍 파싱은 동일(OpenAI 호환)하되 두 가지만 다르다:
    - reasoning 파라미터: DeepSeek `thinking:{type}` 대신 OpenRouter `reasoning:{enabled}`.
    - reasoning 텍스트가 delta.reasoning으로 오므로 runtime 계약(reasoning_content)에 맞춰 매핑.
    reasoning_details 왕복 보존은 하지 않는다(에이전트 루프는 매 턴 새로 추론해도 정상 동작).
    # ponytail: reasoning_details 미보존 — 추론 연속성 최적화가 필요하면 그때 추가.
    """

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base = base_url.rstrip("/")

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
            "reasoning": {"enabled": bool(thinking)},
        }
        if thinking and reasoning_effort:
            payload["reasoning"]["effort"] = reasoning_effort
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
                    "X-Title": "FORGE",  # OpenRouter 대시보드 표기용(선택)
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
                    delta = dict(choices[0].get("delta", {})) if choices else {}
                    # OpenRouter는 추론 텍스트를 delta.reasoning으로 준다 → runtime 계약명으로 매핑.
                    if "reasoning" in delta and "reasoning_content" not in delta:
                        delta["reasoning_content"] = delta.pop("reasoning")

                    usage = chunk.get("usage")
                    if usage:
                        # OpenAI usage → runtime 기대 키(cache hit/miss)로 매핑. 원본도 보존.
                        details = usage.get("prompt_tokens_details") or {}
                        cached = int(details.get("cached_tokens") or 0)
                        prompt = int(usage.get("prompt_tokens") or 0)
                        delta["usage"] = {
                            "prompt_tokens": prompt,
                            "completion_tokens": int(usage.get("completion_tokens") or 0),
                            "prompt_cache_hit_tokens": cached,
                            "prompt_cache_miss_tokens": max(0, prompt - cached),
                        }

                    if delta:
                        yield delta
