"""크래시로 'running'에 갇힌 예약 잡 복구(reset_orphaned_running_jobs) — 실제 DB 왕복.

자기 잡만 생성·정리해 부작용을 남기지 않는다. 기동 시점엔 실행 중 잡이 없다는 전제와
동일한 안전성(대칭: take_interrupted_runs).
실행: python -m pytest test_scheduler_recovery.py -q
"""
import asyncio

from app.db import store


def test_reset_orphaned_running_jobs():
    async def go():
        job = await store.create_job({
            "name": "orphan-recovery-test", "prompt": "noop",
            "recurrence": "one_shot", "workspace_path": "/tmp",
        })
        jid = job["id"]
        try:
            # 크래시로 'running'에 갇힌 상태 재현
            await store.update_job(jid, {"status": "running"})
            assert (await store.get_job(jid))["status"] == "running"

            # 기동 복구: running → scheduled(재선점 가능)
            n = await store.reset_orphaned_running_jobs()
            assert n >= 1
            assert (await store.get_job(jid))["status"] == "scheduled"
        finally:
            await store.delete_job(jid)

    asyncio.run(go())
