"""승인·refinement·모호한 도구 처리 — store.py에서 분리한 도메인 모듈."""
import json
from datetime import datetime, timedelta

from sqlalchemy import select, update

from ..runtime import approvals as _appr
from .models import Approval, Refinement, Session, ToolLedger
from .session import async_session

_DECISIONS = {"approve": "approved", "ignore": "ignored", "rollback": "pending"}


def _refinement_dict(r: Refinement) -> dict:
    return {
        "id": r.id,
        "session_id": r.session_id,
        "type": r.type,
        "scope": r.scope,
        "target": r.target,
        "proposed_change": r.proposed_change,
        "before_text": r.before_text,
        "after_text": r.after_text,
        "evidence_runs": json.loads(r.evidence_runs or "[]"),
        "evidence": json.loads(r.evidence_json or "{}"),
        "failure_pattern": r.failure_pattern,
        "expected_effect": r.expected_effect,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "decided_at": r.decided_at.isoformat() if r.decided_at else "",
    }


async def save_refinement(session_id: str, candidate: dict) -> dict | None:
    """후보 1건 저장. 같은 failure_pattern이 이미 있으면 저장하지 않는다(None).

    같은 실패가 반복될 때마다 같은 후보를 다시 띄우면 알림 소음이 된다.
    사용자가 무시한 후보를 되살리지도 않는다(무시는 결정이다).
    """
    pattern = candidate.get("failure_pattern", "")
    async with async_session() as s:
        if pattern:
            dup = (await s.execute(
                select(Refinement).where(Refinement.failure_pattern == pattern)
            )).scalars().first()
            if dup:
                return None
        row = Refinement(
            session_id=session_id,
            type=candidate.get("type", "skill"),
            scope=candidate.get("scope", "project"),
            target=candidate.get("target", ""),
            proposed_change=candidate.get("proposed_change", ""),
            before_text=candidate.get("before_text", ""),
            after_text=candidate.get("after_text", ""),
            evidence_runs=json.dumps(candidate.get("evidence_runs", []), ensure_ascii=False),
            evidence_json=json.dumps(candidate.get("evidence", {}), ensure_ascii=False),
            failure_pattern=pattern,
            expected_effect=candidate.get("expected_effect", ""),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return _refinement_dict(row)


async def list_refinements(session_id: str = "", limit: int = 10) -> list[dict]:
    """최근 후보(대기 중 + 최근 결정분). 결정된 것도 보여야 rollback을 누를 수 있다."""
    q = select(Refinement).order_by(Refinement.id.desc()).limit(limit)
    if session_id:
        q = select(Refinement).where(Refinement.session_id == session_id) \
            .order_by(Refinement.id.desc()).limit(limit)
    async with async_session() as s:
        rows = (await s.execute(q)).scalars().all()
    return [_refinement_dict(r) for r in rows]


async def decide_refinement(refinement_id: int, decision: str) -> dict | None:
    """승인/무시/되돌리기. 승인은 '기록'일 뿐 파일을 바꾸지 않는다(적용은 다음 단계)."""
    status = _DECISIONS.get(decision)
    if not status:
        return None
    async with async_session() as s:
        row = await s.get(Refinement, refinement_id)
        if not row:
            return None
        row.status = status
        row.decided_at = None if status == "pending" else datetime.utcnow()
        await s.commit()
        await s.refresh(row)
        return _refinement_dict(row)


def _approval_dict(a: Approval) -> dict:
    return {
        "id": a.id, "session_id": a.session_id, "run_id": a.run_id,
        "tool_name": a.tool_name, "args_hash": a.args_hash, "preview": a.preview,
        "status": a.status,
        "requested_at": a.requested_at.isoformat() if a.requested_at else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "expires_at_ts": a.expires_at.timestamp() if a.expires_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "decided_by": a.decided_by,
        "consumed_at": a.consumed_at.isoformat() if a.consumed_at else None,
    }


async def create_approval(approval_id: str, session_id: str, run_id: str, tool_name: str,
                          args_hash: str, preview: str, ttl_seconds: int = 3600) -> None:
    """승인 요청을 requested로 기록한다. 실행 대기(Future)와 별개로 상태를 영속화한다."""
    async with async_session() as s:
        if await s.get(Session, session_id) is None:
            return
        s.add(Approval(
            id=approval_id, session_id=session_id, run_id=run_id, tool_name=tool_name,
            args_hash=args_hash, preview=preview[:2000], status="requested",
            expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
        ))
        await s.commit()


async def get_approval(approval_id: str) -> dict | None:
    async with async_session() as s:
        a = await s.get(Approval, approval_id)
        return _approval_dict(a) if a else None


async def decide_approval(approval_id: str, session_id: str, decision: str,
                          decided_by: str = "user") -> bool:
    """requested → approved|rejected 로 원자·멱등 전이. 조건부 UPDATE(WHERE status='requested'
    AND session_id 일치)라 이미 결정됐거나 다른 session이면 rowcount 0(전이 안 됨)."""
    if decision not in ("approved", "rejected"):
        return False
    async with async_session() as s:
        # 만료되지 않은 requested만 결정 가능 — 만료 정리와 사용자 결정이 경쟁해도 조건부
        # UPDATE라 한 전이만 성공한다(만료됐으면 rowcount 0).
        now = datetime.utcnow()
        res = await s.execute(
            update(Approval)
            .where(Approval.id == approval_id,
                   Approval.session_id == session_id,
                   Approval.status == "requested",
                   (Approval.expires_at.is_(None)) | (Approval.expires_at > now))
            .values(status=decision, decided_at=now, decided_by=decided_by)
        )
        await s.commit()
        return res.rowcount == 1


async def consume_approval(approval_id: str, session_id: str, current_args_hash: str) -> tuple[bool, str]:
    """실제 실행 직전 approved → consumed 로 전이한다. session·status·만료·args_hash를 재검증하고,
    조건부 UPDATE(WHERE status='approved')로 중복 실행을 원자적으로 막는다. (ok, reason)."""
    async with async_session() as s:
        a = await s.get(Approval, approval_id)
        if a is None:
            return False, "not_found"
        ok, why = _appr.can_consume(_approval_dict(a), session_id, current_args_hash,
                                    datetime.utcnow().timestamp())
        if not ok:
            return False, why
        res = await s.execute(
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == "approved")
            .values(status="consumed", consumed_at=datetime.utcnow())
        )
        await s.commit()
        return (res.rowcount == 1), ("ok" if res.rowcount == 1 else "race_lost")


async def list_pending_approvals(session_id: str = "") -> list[dict]:
    """살아있는(requested·미만료) 승인 목록. SSE 재연결 복원용. session_id를 주면 그 세션만.
    만료된 requested는 제외한다(만료 카드를 프런트에 노출하지 않는다)."""
    now = datetime.utcnow()
    async with async_session() as s:
        q = select(Approval).where(
            Approval.status == "requested",
            (Approval.expires_at.is_(None)) | (Approval.expires_at > now))
        if session_id:
            q = q.where(Approval.session_id == session_id)
        res = await s.execute(q.order_by(Approval.requested_at))
        return [_approval_dict(a) for a in res.scalars()]


async def expire_stale_approvals() -> int:
    """만료시각을 넘긴 requested 승인을 expired로 정리한다. 반환: 만료 처리 수."""
    async with async_session() as s:
        res = await s.execute(
            update(Approval)
            .where(Approval.status == "requested", Approval.expires_at < datetime.utcnow())
            .values(status="expired", decided_at=datetime.utcnow(), decided_by="system")
        )
        await s.commit()
        return res.rowcount


async def cancel_approvals(session_id: str, run_id: str = "") -> int:
    """세션(선택적으로 run) 범위의 requested 승인을 cancelled로 원자 전이한다. 세션 취소 시
    미결 승인이 requested로 남아 이후 잘못 소비되는 것을 막는다. 반환: 취소 처리 수."""
    async with async_session() as s:
        q = (update(Approval)
             .where(Approval.status == "requested", Approval.session_id == session_id))
        if run_id:
            q = q.where(Approval.run_id == run_id)
        res = await s.execute(
            q.values(status="cancelled", decided_at=datetime.utcnow(), decided_by="cancel"))
        await s.commit()
        return res.rowcount


async def cleanup_orphan_approvals() -> int:
    """서버 기동 시, 실행 주체(메모리 Future·continuation)를 잃은 모든 requested 승인을
    cancelled로 정리한다. 전체 tool args·실행 continuation이 영속화되지 않는 현재 구조에선
    재시작 후 기존 실행을 이어갈 수 없으므로, 이런 승인을 '실행 가능한 카드'로 복원하지 않는다.
    Auto Resume가 승인형 도구를 다시 수행하려면 새 run에서 새 승인 ID로 다시 요청해야 한다."""
    async with async_session() as s:
        res = await s.execute(
            update(Approval)
            .where(Approval.status == "requested")
            .values(status="cancelled", decided_at=datetime.utcnow(), decided_by="restart"))
        await s.commit()
        return res.rowcount


async def resolve_ambiguous_tool(session_id: str, tool_name: str, args_hash: str) -> None:
    """차단을 한 번 알린 뒤 started 행을 닫는다(reported).

    영구 차단이 아니다 — 목적은 "모르는 채 자동으로 다시 실행하지 않는 것"이지 그 도구를
    영원히 못 쓰게 하는 것이 아니다. 한 번 알렸으면 모델은 상태를 확인하고 판단할 수 있고,
    같은 경고를 반복하면 정상 작업이 막힌다(사용자 취소로 남은 행이 세션을 영영 오염시킨다).
    """
    async with async_session() as s:
        await s.execute(update(ToolLedger).where(
            ToolLedger.session_id == session_id, ToolLedger.tool_name == tool_name,
            ToolLedger.args_hash == args_hash, ToolLedger.status == "started")
            .values(status="reported", completed_at=datetime.utcnow()))
        await s.commit()


async def has_ambiguous_tool(session_id: str, tool_name: str, args_hash: str,
                             exclude_run_id: str = "") -> bool:
    """같은 (session, tool, args)가 이전 run에서 started인 채 끝났는가.

    True면 그 부작용이 실제로 반영됐는지 알 수 없다 — 호출측은 자동 재실행하지 않는다.
    현재 run의 행은 제외한다(내가 방금 연 행이 나를 막으면 정상 실행이 불가능하다)."""
    q = (select(ToolLedger.id)
         .where(ToolLedger.session_id == session_id,
                ToolLedger.tool_name == tool_name,
                ToolLedger.args_hash == args_hash,
                ToolLedger.status == "started"))
    if exclude_run_id:
        q = q.where(ToolLedger.run_id != exclude_run_id)
    async with async_session() as s:
        return (await s.execute(q.limit(1))).scalar_one_or_none() is not None
