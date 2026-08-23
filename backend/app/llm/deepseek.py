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
            "stream_options": {"include_usage": True},
            # DeepSeek V4의 기본값은 thinking=enabled이므로 반드시 명시한다.
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        if tools:
            payload["tools"] = tools
        if thinking and reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
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

                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    usage = chunk.get("usage")

                    # usage는 choices=[]인 별도 마지막 chunk로 올 수 있다.
                    # 런타임이 동일 스트림에서 토큰 사용량을 처리할 수 있도록 병합한다.
                    if usage:
                        delta = dict(delta)
                        delta["usage"] = usage

                    if delta:
                        yield delta

    async def fetch_balance(self) -> dict:
        """계정 잔액 조회 — GET /user/balance (DeepSeek 공식 API).

        balance_infos: 통화별 잔액 목록(보통 CNY 1건). 실패 시 RuntimeError.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=10)) as client:
            resp = await client.get(
                f"{self.base}/user/balance",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"잔액 조회 오류 {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()
