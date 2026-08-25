import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text

from .api.routes import router
from .auth import TokenAuthMiddleware, parse_allowed_origins
from .config import settings
from .db import store
from .db.models import Base
from .db.session import engine
from . import errors as error_log

# create_all은 기존 테이블에 새 컬럼을 추가하지 못하므로, 신규 컬럼은 idempotent ALTER로 보강한다.
_COLUMN_PATCHES = [
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS cache_hit_tokens INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS cache_miss_tokens INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS model_calls INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS tool_calls INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS retries INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS compactions INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS elapsed_ms INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS selected_skill_count INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS selected_skills VARCHAR DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS auto_approve BOOLEAN DEFAULT FALSE",
"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS model_tier VARCHAR DEFAULT 'auto'",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS running BOOLEAN DEFAULT FALSE",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS final_status VARCHAR DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS mode VARCHAR DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS compact_summary TEXT DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS compact_covered INTEGER DEFAULT 0",
    "ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS retries INTEGER DEFAULT 0",
    "ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS tool_raw_tokens INTEGER DEFAULT 0",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS tool_visible_tokens INTEGER DEFAULT 0",
    # 컨텍스트 예산을 모델 실제 한도(128k)로 통일 — 옛 256k 세션은 표시가 실제의 절반이었다.
    "UPDATE sessions SET logical_budget = 131072 WHERE logical_budget = 262144",
    # refinements 테이블 — create_all이 새 테이블을 만들지만, 기존 DB에 모델이 늦게
    # 추가된 경우를 대비해 idempotent CREATE TABLE로 보강한다(UndefinedTable 방지).
    "CREATE TABLE IF NOT EXISTS refinements ("
    "id SERIAL PRIMARY KEY, session_id VARCHAR DEFAULT '', type VARCHAR DEFAULT 'skill', "
    "scope VARCHAR DEFAULT 'project', target VARCHAR DEFAULT '', proposed_change TEXT DEFAULT '', "
    "before_text TEXT DEFAULT '', after_text TEXT DEFAULT '', evidence_runs TEXT DEFAULT '[]', "
    "evidence_json TEXT DEFAULT '{}', failure_pattern VARCHAR DEFAULT '', "
    "expected_effect VARCHAR DEFAULT '', status VARCHAR DEFAULT 'pending', "
    "created_at TIMESTAMP DEFAULT now(), decided_at TIMESTAMP)",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 원격 운영 모드 fail-closed 게이트 — 인증 없이 외부에 노출되는 것을 기동 단계에서 막는다.
    from .auth import assert_startup_auth
    assert_startup_auth(settings.require_auth, settings.auth_token)
    # 이벤트 루프 watchdog — 콜백이 루프를 오래 잡으면(동기 블로킹) 경고 로그를 남긴다.
    # 조용한 먹통이 가장 나쁘다: 로그에 "slow callback"이 찍히면 어느 도구가 범인인지 안다.
    # (실제로 grep/list_dir 동기 재귀가 홈 디렉터리에서 서버를 먹통으로 만든 적이 있다.)
    try:
        import asyncio as _aio
        loop = _aio.get_running_loop()
        loop.set_debug(True)
        loop.slow_callback_duration = 1.0  # 1초 이상 루프를 잡은 콜백을 경고
    except Exception:
        pass
    # ── 필수 초기화: DB schema. 실패하면 조용히 넘기지 않는다 — readiness를 false로 두고
    #    구조화 로그를 남긴다. 프로세스를 즉시 죽여 무한 재시작에 빠지지 않게 하되, 준비 안 됨을
    #    /api/ready로 정직하게 알린다. DB가 없으면 resume/scheduler도 시작하지 않는다.
    app.state.ready = False
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in _COLUMN_PATCHES:
                await conn.execute(text(stmt))
        app.state.ready = True
    except Exception as err:
        error_log.record("startup_db", f"DB 스키마 초기화 실패 — 서비스 not-ready: {err}", "")
        yield
        return  # DB 없이 resume/scheduler를 띄우지 않는다(치명 초기화 실패).

    # ── 선택 기능: 하나 실패해도 서비스 전체를 죽이지 않는다. 다만 조용히 넘기지 않고 로그를 남긴다.
    # 재시작으로 중단된 run 복구(auto_resume면 이어서 완주, 아니면 안내만).
    try:
        interrupted = await store.take_interrupted_runs()
        if interrupted:
            if settings.auto_resume:
                from .api.routes import resume_run
                import os as _os

                async def _resume_all(items):
                    for it in items:
                        ws = it["workspace_path"]
                        # 재개 금지: resuming(재개 중 또 죽음, 크래시 루프 가드) / 잘못된 workspace.
                        if (it["final_status"] == "resuming" or not ws
                                or ws == "/" or not _os.path.isdir(ws)):
                            await store.mark_interrupted_note(it["id"])
                            continue
                        await resume_run(it["id"], ws)  # 순차 — 스파이크 방지

                asyncio.create_task(_resume_all(interrupted))
            else:
                for it in interrupted:
                    await store.mark_interrupted_note(it["id"])
    except Exception as err:
        error_log.record("startup_resume", f"중단 run 복구 실패(서비스는 계속): {err}", "")

    # 크래시로 'running'에 갇힌 예약 잡을 되돌려 재선점 가능하게(세션 복구와 대칭).
    try:
        await store.reset_orphaned_running_jobs()
    except Exception as err:
        error_log.record("startup_jobs", f"예약 잡 복구 실패(서비스는 계속): {err}", "")

    # 예약 작업 스케줄러는 DB 준비 후에만 시작(DB next_run_at이 authoritative).
    try:
        from . import scheduler
        scheduler.start()
    except Exception as err:
        error_log.record("startup_scheduler", f"스케줄러 시작 실패(서비스는 계속): {err}", "")
    yield


app = FastAPI(title="FORGE", lifespan=lifespan)

# 토큰 게이트를 CORS보다 바깥(먼저)에 둔다. 토큰 미설정이면 무동작.
if settings.auth_token:
    app.add_middleware(TokenAuthMiddleware, token=settings.auth_token)

app.add_middleware(
    CORSMiddleware,
    # 화이트리스트 설정 시 그 origin만, 미설정이면 '*'(로컬 개발). 원격은 실제 도메인 나열 권장.
    allow_origins=parse_allowed_origins(settings.allowed_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    # liveness — 프로세스가 떠 있으면 200(로드밸런서·모니터링용). DB 상태와 무관.
    return {"ok": True}


@app.get("/api/ready")
async def ready():
    # readiness — 필수 초기화(DB schema)가 끝났을 때만 준비됨. 실패 시 503으로 정직히 알린다.
    r = bool(getattr(app.state, "ready", False))
    return JSONResponse({"ready": r}, status_code=200 if r else 503)


app.include_router(router, prefix="/api")

uploads_dir = Path(__file__).resolve().parent / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # sw.js·index.html은 절대 캐시하지 않는다 — Cloudflare/브라우저가 stale SW를 붙들면
    # 새 배포가 폰에 영원히 전달되지 않는다(구버전 고착의 근본 원인). 해시된 /assets는 불변.
    _NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate"}

    def _needs_no_store(path: str) -> bool:
        return path in ("sw.js", "index.html", "registerSW.js") or path.endswith((
            "sw.js", "push-handler.js", "manifest.webmanifest",
        ))

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = frontend_dist / full_path
        if full_path and candidate.is_file():
            headers = _NO_STORE if _needs_no_store(full_path) else None
            return FileResponse(candidate, headers=headers)
        return FileResponse(frontend_dist / "index.html", headers=_NO_STORE)
