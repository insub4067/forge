from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deep_seek_api_key: str = ""
    deep_seek_model: str = "deepseek-v4-pro"
    llm_provider: str = "deepseek"
    planner_model: str = ""
    coder_model: str = ""
    reviewer_model: str = ""
    debugger_model: str = ""
    vision_model: str = ""
    chat_model: str = ""
    triage_model: str = ""
    planner_pro_model: str = ""
    database_url: str = "postgresql+psycopg://forge:forge@localhost:5432/forge"
    redis_url: str = "redis://localhost:6379"
    workspace: str = str(BASE_DIR.parent.parent)
    logical_budget: int = 262144
    sandbox_image: str = "forge-sandbox:latest"


settings = Settings()

# 모델별 단가 (USD / 1M tokens). 가격이 바뀌면 이 표만 고치면 되고 런타임 로직은
# 손대지 않는다. 표에 없는 모델은 비용 계산에서 제외되고 토큰 계측은 정상 동작한다.
# ⚠️ 아래 값은 예시다 — 실제 청구 전에 DeepSeek 공식 단가로 교체할 것.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"cache_miss": 0.28, "cache_hit": 0.028, "output": 0.42},
    "deepseek-v4-pro": {"cache_miss": 0.55, "cache_hit": 0.055, "output": 2.19},
    "deepseek-v4-flash-vision-exp": {"cache_miss": 0.28, "cache_hit": 0.028, "output": 0.42},
}
