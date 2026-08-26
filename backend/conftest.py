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
import tempfile

_TMP_LOGS = os.environ.setdefault(
    "FORGE_LOG_DIR", tempfile.mkdtemp(prefix="forge-test-logs-"))


def pytest_report_header(config):
    return f"eventlog → {_TMP_LOGS} (운영 logs/ 격리)"


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
