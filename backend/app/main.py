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
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS running BOOLEAN DEFAULT FALSE",
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS final_status VARCHAR DEFAULT ''",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in _COLUMN_PATCHES:
                await conn.execute(text(stmt))
        # 재시작으로 중단된 run 정리(복구 메시지 + 플래그 해제).
        await store.reconcile_interrupted_runs()
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
