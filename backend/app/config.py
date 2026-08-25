from pathlib import Path

from pydantic import AliasChoices, Field
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
    # ── 컨텍스트 예산: provider capability와 FORGE 운영 정책을 분리한다 ──
    # working_context_budget: 성능·비용을 위한 FORGE 운영 정책(하드 한도가 아니다). compaction과
    #   emergency block은 이 값 기준으로 동작한다. logical_budget과 동일 값을 유지(하위호환 — 기존
    #   env·DB·UI context gauge가 logical_budget을 그대로 쓴다). 런타임은 이 두 값을 같은 것으로 본다.
    # hard_context_limit: provider/model의 공식 컨텍스트 상한(용량 metadata). 운영 예산은 항상 이보다
    #   작아야 하며, 여기서 단순히 예산을 이 값으로 키우지 않는다(모델단 절단·리셋 회귀 방지).
    # max_output_tokens: provider/model의 최대 출력 토큰(용량 metadata).
    # compaction_threshold / emergency_block_threshold: working budget 대비 비율(운영 정책).
    #   (확인하지 못한 provider 사양은 추측하지 않는다 — 아래 기본값은 조정 가능한 metadata다.)
    logical_budget: int = 131072              # = working_context_budget (하위호환 이름 유지)
    working_context_budget: int = 131072      # 운영 예산(= logical_budget). 명시적 개념 이름.
    hard_context_limit: int = 1_000_000       # provider 공식 컨텍스트 상한(metadata, 조정 가능)
    max_output_tokens: int = 8192             # provider 최대 출력(metadata, 조정 가능)
    compaction_threshold: float = 0.75        # working budget의 이 비율에서 압축 시작
    emergency_block_threshold: float = 0.95   # working budget의 이 비율에서 하드 블록
    sandbox_image: str = "forge-sandbox:latest"
    # bash 실행 모드. "docker"(기본, 격리·안전) | "host"(호스트 직접 실행 — 자기검증·
    # 풀파워 가능하지만 에이전트가 맥 전체에 접근. 신뢰하는 개인 환경에서만 옵트인).
    sandbox_mode: str = "docker"
    # 앱 레벨 토큰 게이트(defense-in-depth). 설정 시 모든 /api 요청에 토큰 요구.
    # 미설정이면 무동작 — Cloudflare Access + 127.0.0.1 바인딩에만 의존(auth.py 참고).
    # 문서·기동 메시지가 FORGE_ 접두사를 안내하므로 FORGE_AUTH_TOKEN을 우선 읽되, 기존
    # 접두사 없는 이름도 계속 인식한다(전역 env_prefix는 .env의 다른 무접두 키를 깨므로 쓰지 않는다).
    auth_token: str = Field("", validation_alias=AliasChoices("FORGE_AUTH_TOKEN", "AUTH_TOKEN"))
    # 원격 운영 모드. True면 fail-closed — auth_token이 없으면 서버가 기동을 거부한다.
    # 기본 False(로컬 개발): 기존 동작 그대로. 외부 노출 배포는 FORGE_REQUIRE_AUTH=1로 켠다.
    require_auth: bool = Field(False, validation_alias=AliasChoices("FORGE_REQUIRE_AUTH", "REQUIRE_AUTH"))
    # 허용 CORS origin(콤마 구분). 설정 시 화이트리스트, 미설정이면 '*'(로컬 개발 기본).
    # 외부 노출 배포는 실제 도메인만 나열해 cross-origin 접근을 좁힌다.
    allowed_origins: str = Field("", validation_alias=AliasChoices("FORGE_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"))
    # skill 주입 전면 비활성(skill 효과 A/B 실험용). 기본 False.
    skills_off: bool = False
    # Task IR 인터프리터(Phase 1) 활성화. 기본 False — off면 완전 스킵(동작·비용 불변). A/B로
    # 켜서 관찰한다(현재는 관찰 전용: task_ir 이벤트만 발행하고 라우팅 결정을 바꾸지 않는다).
    task_ir_enabled: bool = False
    # Developer를 항상 pro로(실험용). 기본 False — 평소 flash+think-medium, 실패 시에만 pro 승격.
    developer_pro: bool = False
    # 작업(run) 1회 비용 상한(USD). 누적 비용이 넘으면 안전하게 중단한다 — 무인/자동승인
    # 실행의 runaway 비용을 막는 가드레일. 정상 작업(관측상 ~$1 이하)은 안 건드리고 폭주만
    # 잡도록 넉넉히. 0이면 무제한. 세션별로 UI/set_budget로 재정의 가능.
    session_budget_usd: float = 2.0
    # 작업 완료(검증 통과) 시 durable 프로젝트 지식을 ROOM_MEMORY.md에 자동 적립한다(다음 세션이
    # 재설명 없이 잇게). 검증된 것만·dedup·크기 상한. 끄려면 PROJECT_MEMORY=0.
    project_memory: bool = True
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
# DeepSeek 공식 단가(2024-12 기준) 기준 — deepseek-v4-flash는 deepseek-chat(V3),
# deepseek-v4-pro는 deepseek-reasoner(R1)에 대응한다.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"cache_miss": 0.27, "cache_hit": 0.07, "output": 1.10},
    "deepseek-v4-pro": {"cache_miss": 0.55, "cache_hit": 0.14, "output": 2.19},
    "deepseek-v4-flash-vision-exp": {"cache_miss": 0.27, "cache_hit": 0.07, "output": 1.10},
}
