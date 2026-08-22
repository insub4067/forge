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
    database_url: str = "postgresql+psycopg://forge:forge@localhost:5432/forge"
    redis_url: str = "redis://localhost:6379"
    workspace: str = str(BASE_DIR.parent.parent)
    logical_budget: int = 262144
    sandbox_image: str = "forge-sandbox:latest"


settings = Settings()
