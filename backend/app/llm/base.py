from typing import Any, AsyncIterator, Protocol


class LLMAdapter(Protocol):
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """스트리밍 채팅. delta dict를 yield한다.

        delta는 다음 키를 가질 수 있다:
        - reasoning_content: 추론 텍스트
        - content: 답변 텍스트
        - tool_calls: [{index, id?, function: {name?, arguments?}}]
        - usage: {prompt_tokens, completion_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens}
        """
        ...
