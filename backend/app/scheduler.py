"""Scheduled / Condition Jobs — 시간 Trigger를 기존 AgentRuntime 앞에 얇게 추가.

DB의 next_run_at(naive UTC)이 authoritative source다. 서버가 재시작해도
enabled 잡은 next_run_at으로 복원된다. Scheduler는 언제 실행할지만 정하고,
plan/code/review는 기존 AgentRuntime이 그대로 담당한다.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfo

from .db import store
from . import errors as error_log

_TASK = None


def _compute_next(job: dict, from_utc: datetime) -> datetime | None:
    """반복 잡의 다음 실행 시각(aware UTC). one-shot이면 None."""
    rec = job.get("recurrence") or ""
    tz = ZoneInfo(job.get("timezone") or "Asia/Seoul")
    if rec == "interval":
        try:
            mins = max(1, int(job.get("recurrence_value") or "60"))
        except ValueError:
            mins = 60
        return from_utc + timedelta(minutes=mins)
    if rec == "daily":
        try:
            hh, mm = (job.get("recurrence_value") or "09:00").split(":")
            hh, mm = int(hh), int(mm)
        except ValueError:
            hh, mm = 9, 0
        local_now = from_utc.astimezone(tz)
        nxt = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= local_now:
            nxt += timedelta(days=1)
        return nxt.astimezone(_tz.utc)
    return None


async def run_job(job: dict) -> None:
    """예약 잡 1회 실행 — 기존 runtime 재사용. 중복 실행은 SKIP."""
    from .api.routes import runtime, _notify_done  # 지연 import(순환 방지)

    sid = job.get("session_id") or ""
    if not sid:
        sid = uuid.uuid4().hex
        await store.update_job(job["id"], {"session_id": sid})
    await store.ensure_session(sid, job.get("name") or "예약 작업", job.get("workspace_path"))
    if runtime.is_running(sid):
        return  # 이전 실행 진행 중 → 중복 AgentRun 생성 금지

    await store.update_job(job["id"], {"status": "running"})
    runtime.set_auto_approve(sid, bool(job.get("auto_approve", True)))
    history = await store.load_history(sid)
    history.append({"role": "user", "content": f"[예약 작업] {job.get('prompt', '')}"})
    await store.save_history(sid, history)
    await store.mark_running(sid, True)

    result = "완료"
    try:
        async def _emit(_evt):
            return None  # 관중 없음 — eventlog/status가 기록
        new_history = await runtime.run(history, _emit, sid, job.get("workspace_path"))
        await store.save_history(sid, new_history)
        await _notify_done(sid, new_history)
    except Exception as err:
        result = f"오류: {err}"
        error_log.record("job_run", str(err), sid)
    finally:
        await store.mark_running(sid, False)
        runtime.cleanup_session(sid)

    now = datetime.now(_tz.utc)
    nxt = _compute_next(job, now)
    fields = {"last_run_at": now.replace(tzinfo=None), "last_result": result[:500]}
    if nxt:
        fields.update({"next_run_at": nxt.replace(tzinfo=None), "status": "scheduled"})
    else:
        fields.update({"next_run_at": None, "enabled": False, "status": "done"})
    await store.update_job(job["id"], fields)


async def _loop() -> None:
    while True:
        try:
            for job in await store.due_jobs(datetime.utcnow()):
                await run_job(job)
        except Exception as err:
            error_log.record("scheduler", str(err), "")
        await asyncio.sleep(20)


def start() -> None:
    global _TASK
    if _TASK is None:
        _TASK = asyncio.create_task(_loop())
