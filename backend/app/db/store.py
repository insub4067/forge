"""DB 접근 계층 — 도메인별 모듈로 분리된 함수를 재-export한다.

이동된 구현:
- session.py    — ensure_session (공통 세션 획득)
- rooms.py      — 룸/세션 CRUD·상태·컨텍스트/설정
- history.py    — 히스토리 저장·검색
- approvals.py  — 승인·refinement·모호한 도구 처리
- ledger.py     — 실행 기록·비용(ledger)·AgentRun 메트릭

기존 `from ..db import store` 호출부가 깨지지 않도록 이름을 그대로 노출한다.
"""
import re

from sqlalchemy import delete, select, update

from .models import AcceptanceGate, PushDevice, ScheduledJob, Task
from .session import async_session, ensure_session

from .approvals import (cancel_approvals, cleanup_orphan_approvals, consume_approval,
                        create_approval, decide_approval, decide_refinement,
                        expire_stale_approvals, get_approval, has_ambiguous_tool,
                        list_pending_approvals, list_refinements, resolve_ambiguous_tool,
                        save_refinement)
from .history import load_history, save_history, search_messages
from .ledger import (admin_stats, all_runs_for_cost, ledger_complete, ledger_start,
                     metrics_summary, save_agent_run, session_agent_runs, session_metrics,
                     set_session_final_status)
from .rooms import (create_room, delete_room, get_room, list_rooms, mark_interrupted_note,
                    mark_running, reconcile_interrupted_runs, session_state,
                    set_session_auto_approve, set_session_compaction, set_session_model_tier,
                    take_interrupted_runs, update_context_usage, update_room_mode,
                    update_room_title, update_room_workspace, get_session_auto_approve,
                    get_session_compaction, get_session_model_tier)

__all__ = [
    # session.py
    "ensure_session",
    # rooms.py
    "create_room", "update_room_workspace", "update_room_mode", "update_room_title",
    "session_state", "get_room", "delete_room", "list_rooms", "update_context_usage",
    "mark_running", "set_session_auto_approve", "get_session_auto_approve",
    "set_session_model_tier", "get_session_model_tier", "set_session_compaction",
    "get_session_compaction", "reconcile_interrupted_runs", "take_interrupted_runs",
    "mark_interrupted_note",
    # history.py
    "load_history", "save_history", "search_messages",
    # approvals.py
    "create_approval", "get_approval", "decide_approval", "consume_approval",
    "list_pending_approvals", "expire_stale_approvals", "cancel_approvals",
    "cleanup_orphan_approvals", "resolve_ambiguous_tool", "has_ambiguous_tool",
    "save_refinement", "list_refinements", "decide_refinement",
    # ledger.py
    "ledger_start", "ledger_complete", "save_agent_run", "set_session_final_status",
    "session_agent_runs", "session_metrics", "all_runs_for_cost", "metrics_summary",
    "admin_stats",
    # store.py 잔존 (tasks/gates/jobs/devices)
    "merge_tasks", "replace_tasks", "list_tasks", "merge_gates", "replace_gates",
    "list_gates", "save_gate_result", "delete_gates", "register_device", "list_devices",
    "delete_device", "all_subscriptions", "create_job", "list_jobs", "get_job",
    "update_job", "delete_job", "due_jobs", "reset_orphaned_running_jobs", "claim_job",
]

_PROCESS_GATE_STATUS = ("passed", "failed")



def task_key(title: str) -> str:
    """태스크 동일성 키. 모델이 같은 태스크의 제목에 괄호 주석을 덧붙이거나
    구두점을 바꿔도 같은 태스크로 본다("A" ↔ "A (이미 구현·테스트 완료)")."""
    t = re.sub(r"[(\[（【].*?[)\]）】]", " ", title or "")
    t = re.sub(r"[\s·,.:;\-—~/]+", " ", t).strip().lower()
    return t


def _match_task(existing: list[dict], key: str, used: set) -> dict | None:
    """같은 키 우선, 없으면 접두 일치(6자 이상 — 짧은 제목의 오매칭 방지)."""
    if not key:
        return None
    for e in existing:
        if e.get("id") in used:
            continue
        ek = task_key(e.get("title", ""))
        if ek == key:
            return e
    for e in existing:
        if e.get("id") in used:
            continue
        ek = task_key(e.get("title", ""))
        if len(key) >= 6 and len(ek) >= 6 and (ek.startswith(key) or key.startswith(ek)):
            return e
    return None


def merge_tasks(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """태스크 신원을 유지한 병합(순수 함수 — DB 없이 검증 가능).

    모델은 매번 전체 목록을 다시 보내고 제목도 조금씩 고쳐 쓴다. 제목을 신원으로
    삼으면 같은 태스크가 새 태스크로 다시 생겨 목록이 중복된다. 그래서 키로 기존
    태스크를 찾아 **id와 최초 제목을 유지**하고 상태/진행률만 갱신한다.
    한 요청 안에 같은 키가 두 번 오면 첫 번째만 남긴다.
    반환 항목의 id가 None이면 새로 만들 태스크, 아니면 기존 태스크 갱신.
    """
    out: list[dict] = []
    used: set = set()
    seen: set = set()
    for t in incoming:
        title = str(t.get("title", "")).strip()
        if not title:
            continue
        key = task_key(title)
        if key in seen:
            continue
        seen.add(key)
        m = _match_task(existing, key, used)
        prog = t.get("progress")
        if m:
            used.add(m.get("id"))
            out.append({
                "id": m.get("id"),
                "title": m.get("title", title),   # 제목은 처음 것을 유지(표시 흔들림 방지)
                "status": str(t.get("status", m.get("status", "todo"))),
                "progress": int(prog if prog is not None else m.get("progress", 0) or 0),
            })
        else:
            out.append({
                "id": None,
                "title": title,
                "status": str(t.get("status", "todo")),
                "progress": int(prog or 0),
            })
    return out


async def replace_tasks(session_id: str, tasks: list[dict]) -> list[dict]:
    """모델이 준 목록으로 태스크를 갱신하고, 신원이 유지된 최종 목록을 반환한다."""
    async with async_session() as s:
        rows = (await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )).scalars().all()
        by_id = {r.id: r for r in rows}
        existing = [{"id": r.id, "title": r.title, "status": r.status,
                     "progress": r.progress} for r in rows]
        merged = merge_tasks(existing, tasks)
        keep: set = set()
        for m in merged:
            row = by_id.get(m["id"]) if m["id"] is not None else None
            if row is None:
                row = Task(session_id=session_id, title=m["title"],
                           status=m["status"], progress=m["progress"])
                s.add(row)
            else:
                row.status = m["status"]
                row.progress = m["progress"]
                keep.add(row.id)
        for r in rows:
            if r.id not in keep:
                await s.delete(r)
        await s.commit()
        result = (await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )).scalars().all()
        return [{"id": r.id, "title": r.title, "status": r.status,
                 "progress": r.progress} for r in result]


async def list_tasks(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )
        return [
            {"id": t.id, "title": t.title, "status": t.status, "progress": t.progress}
            for t in result.scalars()
        ]


def _gate_dict(g: AcceptanceGate) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "description": g.description,
        "verification_method": g.verification_method,
        "expected_result": g.expected_result,
        "status": g.status,
        "evidence": g.evidence,
        "failure_reason": g.failure_reason,
        "requirement_id": getattr(g, "requirement_id", "") or "",
    }


def merge_gates(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """gate 신원을 유지한 병합(순수 함수). 태스크 병합(merge_tasks)과 같은 원리.

    신원은 제목 키(task_key)다. 모델이 매번 전체 목록을 다시 보내므로 id·최초 제목을
    유지하고 description/verification_method/expected_result만 갱신한다.
    status는 clamp가 이미 적용된 모델 상태지만, 기존이 프로세스 상태(passed/failed)면
    모델의 재선언으로 되돌리지 않는다(프로세스 소유권 보호).
    """
    out: list[dict] = []
    used: set = set()
    seen: set = set()
    for g in incoming:
        title = str(g.get("title", "")).strip()
        if not title:
            continue
        key = task_key(title)
        if key in seen:
            continue
        seen.add(key)
        m = _match_task(existing, key, used)
        if m:
            used.add(m.get("id"))
            old_status = m.get("status", "")
            if old_status in _PROCESS_GATE_STATUS:
                status = old_status          # 프로세스 소유 상태는 모델이 되돌릴 수 없다
            else:
                status = str(g.get("status", old_status)) or old_status
            out.append({
                "id": m.get("id"),
                "title": m.get("title", title),          # 최초 제목 유지
                "description": str(g.get("description") or m.get("description") or ""),
                "verification_method": str(g.get("verification_method") or m.get("verification_method") or ""),
                "expected_result": str(g.get("expected_result") or m.get("expected_result") or ""),
                "status": status,
                "evidence": m.get("evidence", "{}"),
                "failure_reason": str(g.get("failure_reason") or m.get("failure_reason") or ""),
                "requirement_id": str(g.get("requirement_id") or m.get("requirement_id") or ""),
            })
        else:
            out.append({
                "id": None,
                "title": title,
                "description": str(g.get("description") or ""),
                "verification_method": str(g.get("verification_method") or ""),
                "expected_result": str(g.get("expected_result") or ""),
                "status": str(g.get("status", "pending")),
                "evidence": "{}",
                "failure_reason": str(g.get("failure_reason") or ""),
                "requirement_id": str(g.get("requirement_id") or ""),
            })
    # append-preserving(P0-2): 모델이 payload에서 빠뜨린 기존 gate는 조용히 삭제하지 않고
    # 그대로 보존한다. 요구사항을 실수로 누락하는 것만으로 완료 조건(gate)이나 process-owned
    # evidence(passed/failed)가 사라지면 안 된다. 제거가 필요하면 모델이 그 gate를 다시 보내며
    # status=abandoned로 명시 전이해야 한다(그건 위 incoming 경로에서 처리·기록된다).
    for e in existing:
        if e.get("id") not in used:
            out.append(dict(e))
    return out


async def replace_gates(session_id: str, gates: list[dict]) -> list[dict]:
    """모델이 준 목록으로 gate를 갱신하고, 신원이 유지된 최종 목록을 반환한다."""
    async with async_session() as s:
        rows = (await s.execute(
            select(AcceptanceGate).where(AcceptanceGate.session_id == session_id).order_by(AcceptanceGate.id)
        )).scalars().all()
        by_id = {r.id: r for r in rows}
        existing = [_gate_dict(r) for r in rows]
        merged = merge_gates(existing, gates)
        keep: set = set()
        for m in merged:
            row = by_id.get(m["id"]) if m["id"] is not None else None
            if row is None:
                row = AcceptanceGate(session_id=session_id, title=m["title"],
                                     description=m["description"],
                                     verification_method=m["verification_method"],
                                     expected_result=m["expected_result"],
                                     status=m["status"], failure_reason=m["failure_reason"],
                                     requirement_id=m.get("requirement_id", ""))
                s.add(row)
            else:
                row.title = m["title"]
                row.description = m["description"]
                row.verification_method = m["verification_method"]
                row.expected_result = m["expected_result"]
                row.status = m["status"]
                row.failure_reason = m["failure_reason"]
                row.requirement_id = m.get("requirement_id", "")
                keep.add(row.id)
        for r in rows:
            if r.id not in keep:
                await s.delete(r)
        await s.commit()
        result = (await s.execute(
            select(AcceptanceGate).where(AcceptanceGate.session_id == session_id).order_by(AcceptanceGate.id)
        )).scalars().all()
        return [_gate_dict(r) for r in result]


async def list_gates(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(AcceptanceGate).where(AcceptanceGate.session_id == session_id).order_by(AcceptanceGate.id)
        )
        return [_gate_dict(r) for r in result.scalars()]


async def save_gate_result(session_id: str, gate_id: int, status: str,
                           evidence: str, failure_reason: str = "") -> None:
    """gate의 검증 결과를 기록한다 — 프로세스 전용(모델은 호출하지 않는다)."""
    async with async_session() as s:
        row = (await s.execute(
            select(AcceptanceGate).where(AcceptanceGate.id == gate_id,
                                        AcceptanceGate.session_id == session_id)
        )).scalar_one_or_none()
        if row is None:
            return
        row.status = status
        row.evidence = evidence
        row.failure_reason = failure_reason
        await s.commit()


async def delete_gates(session_id: str) -> None:
    """테스트 정리용 — 세션의 gate를 모두 지운다."""
    from sqlalchemy import delete as sa_delete
    async with async_session() as s:
        await s.execute(sa_delete(AcceptanceGate).where(AcceptanceGate.session_id == session_id))
        await s.commit()


async def register_device(name: str, endpoint: str, subscription_json: str) -> None:
    """푸시 기기 등록/갱신(endpoint로 중복 방지)."""
    async with async_session() as s:
        result = await s.execute(select(PushDevice).where(PushDevice.endpoint == endpoint))
        dev = result.scalar_one_or_none()
        if dev:
            dev.subscription_json = subscription_json
            if name:
                dev.name = name
        else:
            s.add(PushDevice(name=name, endpoint=endpoint, subscription_json=subscription_json))
        await s.commit()


async def list_devices() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(select(PushDevice).order_by(PushDevice.created_at.desc()))
        return [
            {
                "id": d.id,
                "name": d.name,
                "created_at": d.created_at.isoformat() if d.created_at else "",
                "last_seen": d.last_seen.isoformat() if d.last_seen else "",
            }
            for d in result.scalars()
        ]


async def delete_device(device_id: int) -> None:
    async with async_session() as s:
        await s.execute(delete(PushDevice).where(PushDevice.id == device_id))
        await s.commit()


async def all_subscriptions() -> list[dict]:
    """모든 기기의 push 구독 정보(발송용)."""
    import json as _json
    async with async_session() as s:
        result = await s.execute(select(PushDevice))
        out = []
        for d in result.scalars():
            try:
                out.append(_json.loads(d.subscription_json))
            except Exception:
                continue
        return out


def _job_dict(j) -> dict:
    return {
        "id": j.id, "name": j.name, "prompt": j.prompt,
        "workspace_path": j.workspace_path, "session_id": j.session_id,
        "timezone": j.timezone,
        "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
        "recurrence": j.recurrence, "recurrence_value": j.recurrence_value,
        "auto_approve": j.auto_approve, "enabled": j.enabled, "status": j.status,
        "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
        "last_result": j.last_result,
        "retries": j.retries, "max_retries": j.max_retries,
    }


async def create_job(data: dict) -> dict:
    async with async_session() as s:
        j = ScheduledJob(
            name=data.get("name", ""), prompt=data.get("prompt", ""),
            workspace_path=data.get("workspace_path", ""),
            session_id=data.get("session_id", ""),
            timezone=data.get("timezone", "Asia/Seoul"),
            next_run_at=data.get("next_run_at"),
            recurrence=data.get("recurrence", ""),
            recurrence_value=data.get("recurrence_value", ""),
            auto_approve=bool(data.get("auto_approve", True)),
            max_retries=int(data.get("max_retries", 0) or 0),
        )
        s.add(j)
        await s.commit()
        await s.refresh(j)
        return _job_dict(j)


async def list_jobs() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(select(ScheduledJob).order_by(ScheduledJob.created_at.desc()))
        return [_job_dict(j) for j in result.scalars()]


async def get_job(job_id: int) -> dict | None:
    async with async_session() as s:
        j = await s.get(ScheduledJob, job_id)
        return _job_dict(j) if j else None


async def update_job(job_id: int, fields: dict) -> None:
    async with async_session() as s:
        j = await s.get(ScheduledJob, job_id)
        if not j:
            return
        for k, v in fields.items():
            if hasattr(j, k):
                setattr(j, k, v)
        await s.commit()


async def delete_job(job_id: int) -> None:
    async with async_session() as s:
        await s.execute(delete(ScheduledJob).where(ScheduledJob.id == job_id))
        await s.commit()


async def due_jobs(now_utc) -> list[dict]:
    """실행 시각이 지난 enabled 잡. next_run_at이 authoritative."""
    async with async_session() as s:
        result = await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.enabled == True,  # noqa: E712
                ScheduledJob.next_run_at.is_not(None),
                ScheduledJob.next_run_at <= now_utc,
                ScheduledJob.status != "running",
            )
        )
        return [_job_dict(j) for j in result.scalars()]


async def reset_orphaned_running_jobs() -> int:
    """기동 시 status='running'에 갇힌 예약 잡을 'scheduled'로 되돌린다(재선점 가능화).

    프로세스가 잡 실행 중 하드 크래시하면 finally/상태 갱신이 돌지 못해 잡이 'running'에
    영구히 갇히고, claim_job(status!='running')이 다시 선점하지 못해 재실행이 막힌다.
    세션 쪽 take_interrupted_runs와 대칭인 잡 버전이다. 기동 시점엔 실행 중인 잡이 없으므로
    'running' 잡은 전부 크래시 고아 → 되돌려도 안전하다. 이후 next_run_at/재시도 정책이
    정상 처리한다. 반환: 되돌린 잡 수."""
    async with async_session() as s:
        result = await s.execute(
            update(ScheduledJob)
            .where(ScheduledJob.status == "running")
            .values(status="scheduled")
        )
        await s.commit()
        return result.rowcount or 0


async def claim_job(job_id: int) -> bool:
    """잡을 원자적으로 선점한다. 이미 running이면 False — 중복 실행 방지."""
    async with async_session() as s:
        result = await s.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.id == job_id,
                ScheduledJob.status != "running",
            )
            .values(status="running")
        )
        await s.commit()
        return result.rowcount > 0
