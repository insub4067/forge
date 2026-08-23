import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text

from .api.routes import router
from .auth import TokenAuthMiddleware
from .config import settings
from .db import store
from .db.models import Base
from .db.session import engine

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
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in _COLUMN_PATCHES:
                await conn.execute(text(stmt))
        # 재시작으로 중단된 run 처리 — auto_resume면 저장된 history에서 이어서 완주,
        # 아니면 안내 메시지만 남긴다.
        interrupted = await store.take_interrupted_runs()
        if interrupted:
            if settings.auto_resume:
                from .api.routes import resume_run

                import os as _os

                async def _resume_all(items):
                    for it in items:
                        ws = it["workspace_path"]
                        # 재개하지 않는 조건(안내만 남김):
                        # - resuming: 재개 중 또 죽은 것 → 재재개 금지(크래시 루프 가드).
                        # - workspace가 없거나/루트("/")거나/실제 디렉터리가 아님 → 잘못된 세션.
                        #   (ws="/"에서 전체 파일시스템 스캔 등으로 서버가 위험해지는 것을 막는다.)
                        if (it["final_status"] == "resuming" or not ws
                                or ws == "/" or not _os.path.isdir(ws)):
                            await store.mark_interrupted_note(it["id"])
                            continue
                        await resume_run(it["id"], ws)  # 순차 — 스파이크 방지

                asyncio.create_task(_resume_all(interrupted))
            else:
                for it in interrupted:
                    await store.mark_interrupted_note(it["id"])
    except Exception:
        pass
    # 예약 작업 스케줄러 시작(DB next_run_at이 authoritative → 재시작 복원).
    from . import scheduler
    scheduler.start()
    yield


app = FastAPI(title="FORGE", lifespan=lifespan)

# 토큰 게이트를 CORS보다 바깥(먼저)에 둔다. 토큰 미설정이면 무동작.
if settings.auth_token:
    app.add_middleware(TokenAuthMiddleware, token=settings.auth_token)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"ok": True}


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
