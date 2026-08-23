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
    # OpenRouter(멀티프로바이더 실험) — 모델 문자열에 "/"가 있으면 이 키로 OpenRouter를 호출한다.
    # 키는 기존 .env의 OX_ALPHA_API_KEY를 재사용(Ox가 OpenRouter였음).
    ox_alpha_api_key: str = ""
    openrouter_base: str = "https://openrouter.ai/api/v1"
    # 잔액 표시용 환율(USD→CNY 근사). DeepSeek 잔액 API는 CNY로 반환한다.
    usd_cny_rate: float = 7.2
    # 잔액 영역 탭 시 안내하는 충전 화면 URL(DeepSeek 플랫폼).
    top_up_url: str = "https://platform.deepseek.com/top_up"
    coder_model: str = ""  # 하위호환 — developer_model 미설정 시 fallback
    developer_model: str = ""      # 통합 Developer(설계+구현+자체검증). 기본 flash+think-medium
    developer_pro_model: str = ""  # 실패 시 승격 모델(기본 deep_seek_model=pro)
    vision_model: str = ""
    chat_model: str = ""           # 단순 대화 — 최저가 flash no-think
    triage_model: str = ""         # chat vs code 라우터 — 최저가 flash
    database_url: str = "postgresql+psycopg://forge:forge@localhost:5432/forge"
    redis_url: str = "redis://localhost:6379"
    workspace: str = str(BASE_DIR.parent.parent)
    # 컨텍스트 예산 — DeepSeek 실제 한도(~128k)에 맞춘다. 이전 값(256k)은 모델 한도의 2배라
    # compaction(예산×0.75)이 영영 안 돌고, 128k에서 모델단이 먼저 앞부분을 잘라 "리셋"처럼
    # 보였다. 128k로 맞추면 96k에서 요약 압축이 먼저 돈다.
    logical_budget: int = 131072
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
    # 작업 성공 완료 시 하네스가 자동으로 git commit(+push)한다 — 커밋 누락 방지. 기본 True.
    # git 워크스페이스이고 변경이 있을 때만. 끄려면 AUTO_COMMIT=0.
    auto_commit: bool = True
    # 서버 재시작으로 중단된 run을 시작 시 저장된 history에서 자동 이어서 완주한다. 기본 True.
    # 크래시 루프 방지: 재개 중 또 중단되면(final_status=resuming) 재재개하지 않는다. 끄려면 AUTO_RESUME=0.
    auto_resume: bool = True
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
