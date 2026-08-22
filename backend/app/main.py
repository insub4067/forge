from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text

from .api.routes import router
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
    yield


app = FastAPI(title="FORGE", lifespan=lifespan)

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

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = frontend_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
