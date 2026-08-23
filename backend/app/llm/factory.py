from ..config import settings
from .deepseek import DeepSeekAdapter


def create_adapter(model: str):
    """provider 설정에 따라 LLM 어댑터를 생성한다.

    새 provider 추가 시 여기서 분기만 늘리면 된다.
    """
    if settings.llm_provider == "deepseek":
        return DeepSeekAdapter(settings.deep_seek_api_key, model)
    raise ValueError(f"지원하지 않는 LLM provider: {settings.llm_provider}")
