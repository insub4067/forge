from ..config import settings
from .deepseek import DeepSeekAdapter
from .openrouter import OpenRouterAdapter


def create_adapter(model: str):
    """모델 문자열로 어댑터를 고른다.

    OpenRouter 슬러그는 "vendor/model" 형태다 — 슬래시가 있으면 OpenRouter로 라우팅해
    프로바이더를 역할별로 섞을 수 있다(예: developer만 Ling/Inkling 실험). 그 외는 DeepSeek.
    """
    if "/" in model:
        return OpenRouterAdapter(settings.ox_alpha_api_key, model)
    if settings.llm_provider == "deepseek":
        return DeepSeekAdapter(settings.deep_seek_api_key, model)
    raise ValueError(f"지원하지 않는 LLM provider: {settings.llm_provider}")
