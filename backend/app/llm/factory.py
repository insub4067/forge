from ..config import settings
from .deepseek import DeepSeekAdapter
from .openrouter import OpenRouterAdapter


def create_adapter(model: str):
    """모델명으로 LLM 어댑터를 고른다.

    Ox 모델(OpenRouter 경유)은 provider와 무관하게 model 기준으로 라우팅한다 —
    Ox는 새 provider가 아니라 Developer가 선택하는 모델이므로(§Ox Alpha 실험).
    새 provider 추가 시 여기서 분기만 늘린다.
    """
    if model == settings.ox_model:
        return OpenRouterAdapter(settings.ox_alpha_api_key, model, settings.ox_base_url)
    if settings.llm_provider == "deepseek":
        return DeepSeekAdapter(settings.deep_seek_api_key, model)
    raise ValueError(f"지원하지 않는 LLM provider: {settings.llm_provider}")
