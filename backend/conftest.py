"""테스트는 운영 로그를 절대 건드리지 않는다.

실제로 일어난 일: `rt.run(...)`을 도는 테스트가 `logs/events-*.jsonl`에
`session_id="s1"` 가짜 run을 쌓았고, gate 커버리지 집계가 그 가짜 run을 실제 사용
데이터로 읽었다. 계측 기반으로 결정을 내리는 프로젝트에서 오염된 telemetry는
잘못된 결론을 만든다.

개별 테스트가 `eventlog.record`를 목킹하는 것에 의존하지 않는다 — 빼먹으면 조용히
오염되기 때문이다. 로그 디렉터리 자체를 임시 경로로 돌려 구조적으로 막는다.
app 모듈이 import되기 **전에** env를 세팅해야 LOG_DIR 상수에 반영된다.
"""
import os
import re
import tempfile
from pathlib import Path

_TMP_LOGS = os.environ.setdefault(
    "FORGE_LOG_DIR", tempfile.mkdtemp(prefix="forge-test-logs-"))


# ── 테스트 DB 격리 ──────────────────────────────────────────────────────
# 라이브 서버가 쓰는 프로덕션 DB(forge)와 절대 공유하지 않는다. 예전엔 테스트가 같은
# forge DB에 DDL·락을 걸어, pytest를 돌리는 동안 라이브 서버의 세션 생성(쓰기)이
# 멈추는 outage가 났다. app import 전에 DATABASE_URL을 <db>_test로 돌려 격리한다.
# (pydantic settings와 engine은 첫 import 시점에 고정되므로 반드시 그 전에 세팅한다.)
def _isolate_test_db() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        os.environ["DATABASE_URL"] = explicit
        return explicit
    base = os.environ.get("DATABASE_URL")
    if not base:  # .env(forge/.env)에서 읽기 — pydantic과 같은 소스
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.lower().startswith("database_url") and "=" in s:
                    base = s.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not base:
        base = "postgresql+psycopg://forge:forge@localhost:5432/forge"
    # 경로 마지막 세그먼트(db 이름)에 _test 접미. 쿼리스트링 보존.
    m = re.match(r"^(.*/)([^/?]+)(\?.*)?$", base)
    test_url = f"{m.group(1)}{m.group(2)}_test{m.group(3) or ''}" if m else f"{base}_test"
    os.environ["DATABASE_URL"] = test_url
    return test_url


_TEST_DB_URL = _isolate_test_db()


def _ensure_database_exists(url: str) -> None:
    """테스트 DB가 없으면 만든다(유지 DB 'postgres'에 붙어 CREATE DATABASE). 이미 있으면 무시.
    못 만들면(권한 없음 등) 명확히 실패시킨다 — 조용히 프로덕션으로 폴백하지 않는다."""
    import psycopg
    from sqlalchemy.engine import make_url
    u = make_url(url)
    if not u.database:
        return
    try:
        with psycopg.connect(host=u.host or "localhost", port=u.port or 5432,
                             user=u.username, password=u.password, dbname="postgres",
                             autocommit=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (u.database,)).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{u.database}"')
    except Exception as e:
        raise RuntimeError(f"테스트 DB 준비 실패({u.database}): {e}") from e


def pytest_report_header(config):
    return f"eventlog → {_TMP_LOGS} (운영 logs/ 격리) · DB → {_TEST_DB_URL}"


import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """테스트 시작 전에 DB 스키마를 생성한다 — 서버 lifespan을 거치지 않는 pytest가
    스키마 사전 존재에 의존하지 않게.

    실제로 일어난 일: CI의 fresh postgres에는 테이블이 없어 DB를 건드리는 테스트가
    `relation "sessions" does not exist`로 무더기 실패했다. 로컬은 dev 서버가 한 번
    만들어놔서 통과하던 착시. 프로덕션과 같은 초기화(create_all + _COLUMN_PATCHES)를
    여기서 한 번 돌려 테스트를 환경-독립적으로 만든다. import는 fixture 안에서 —
    위의 FORGE_LOG_DIR env가 app import 전에 반영되도록.
    """
    import asyncio
    from sqlalchemy import text
    _ensure_database_exists(_TEST_DB_URL)   # 격리 DB(forge_test)가 없으면 먼저 생성
    from app.db.models import Base
    from app.db.session import engine
    from app.main import _COLUMN_PATCHES

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in _COLUMN_PATCHES:
                await conn.execute(text(stmt))

    asyncio.run(_init())
    yield
