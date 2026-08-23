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
    coder_model: str = ""  # 하위호환 — developer_model 미설정 시 fallback
    developer_model: str = ""      # 통합 Developer(설계+구현+자체검증). 기본 flash+think-medium
    developer_pro_model: str = ""  # 실패 시 승격 모델(기본 deep_seek_model=pro)
    vision_model: str = ""
    chat_model: str = ""
    triage_model: str = ""
    database_url: str = "postgresql+psycopg://forge:forge@localhost:5432/forge"
    redis_url: str = "redis://localhost:6379"
    workspace: str = str(BASE_DIR.parent.parent)
    logical_budget: int = 262144
    sandbox_image: str = "forge-sandbox:latest"
    # bash 실행 모드. "docker"(기본, 격리·안전) | "host"(호스트 직접 실행 — 자기검증·
    # 풀파워 가능하지만 에이전트가 맥 전체에 접근. 신뢰하는 개인 환경에서만 옵트인).
    sandbox_mode: str = "docker"
    # 앱 레벨 토큰 게이트(defense-in-depth). 설정 시 모든 /api 요청에 토큰 요구.
    # 미설정이면 무동작 — Cloudflare Access + 127.0.0.1 바인딩에만 의존(auth.py 참고).
    auth_token: str = ""
    # skill 주입 전면 비활성(skill 효과 A/B 실험용). 기본 False.
    skills_off: bool = False
    # Developer를 항상 pro로(실험용). 기본 False — 평소 flash+think-medium, 실패 시에만 pro 승격.
    developer_pro: bool = False
    # Web Push (VAPID). public_key는 브라우저 구독용(비밀 아님). private key는 PEM 파일 경로.
    vapid_public_key: str = "BEdgt7HlWXy3-F1M2MKCkcBrOuW0uWoUvg58WzYFA7z1GBVu9IRGy15NlRP-A1cWINwTO4x4n0HMOmgiukK3HCQ"
    vapid_private_key_path: str = str(BASE_DIR / "vapid_private.pem")
    vapid_subject: str = "mailto:insub4067@gmail.com"


settings = Settings()

# 모델별 단가 (USD / 1M tokens). 가격이 바뀌면 이 표만 고치면 되고 런타임 로직은
# 손대지 않는다. 표에 없는 모델은 비용 계산에서 제외되고 토큰 계측은 정상 동작한다.
# ⚠️ 아래 값은 예시다 — 실제 청구 전에 DeepSeek 공식 단가로 교체할 것.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"cache_miss": 0.28, "cache_hit": 0.028, "output": 0.42},
    "deepseek-v4-pro": {"cache_miss": 0.55, "cache_hit": 0.055, "output": 2.19},
    "deepseek-v4-flash-vision-exp": {"cache_miss": 0.28, "cache_hit": 0.028, "output": 0.42},
}
