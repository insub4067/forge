"""룸/세션 CRUD·상태·설정 — store.py에서 분리한 도메인 모듈."""
import os
import uuid

from sqlalchemy import delete, func, select

from .history import load_history, save_history
from .models import (AcceptanceGate, Approval, Checkpoint, Message, ScheduledJob,
                     Session, Task, ToolLedger)
from .session import async_session


async def create_room(name: str, workspace_path: str = "", mode: str = "") -> str:
    room_id = uuid.uuid4().hex
    locked = bool(workspace_path)
    if not workspace_path:
        workspace_path = os.path.expanduser("~")
    async with async_session() as s:
        s.add(
            Session(
                id=room_id,
                title=name,
                workspace_path=workspace_path,
                workspace_locked=locked,
                mode=mode if mode in ("chat", "work") else "",
            )
        )
        await s.commit()
    return room_id


async def update_room_workspace(session_id: str, workspace_path: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.workspace_path = workspace_path
            await s.commit()


async def update_room_mode(session_id: str, mode: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess and mode in ("chat", "work", ""):
            sess.mode = mode
            await s.commit()


async def update_room_title(session_id: str, title: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.title = title
            await s.commit()


async def session_state(session_id: str) -> dict:
    """세션의 실행 상태(running/final_status). task facade·MCP 결과 조회용."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess is None:
            return {"exists": False, "running": False, "final_status": ""}
        return {"exists": True, "running": bool(sess.running), "final_status": sess.final_status or ""}


async def get_room(session_id: str) -> dict | None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess is None:
            return None
        return {
            "id": sess.id,
            "title": sess.title,
            "workspace_path": sess.workspace_path,
            "workspace_locked": sess.workspace_locked,
            "mode": sess.mode,
            "used_tokens": sess.used_tokens,
            "auto_approve": sess.auto_approve,
            "model_tier": sess.model_tier or "auto",
        }


async def delete_room(session_id: str) -> None:
    async with async_session() as s:
        await s.execute(delete(Message).where(Message.session_id == session_id))
        await s.execute(delete(Task).where(Task.session_id == session_id))
        await s.execute(delete(Checkpoint).where(Checkpoint.session_id == session_id))
        await s.execute(delete(Approval).where(Approval.session_id == session_id))
        # acceptance_gates도 sessions FK — 안 지우면 세션 삭제가 FK 위반으로 실패한다.
        await s.execute(delete(AcceptanceGate).where(AcceptanceGate.session_id == session_id))
        await s.execute(delete(ToolLedger).where(ToolLedger.session_id == session_id))
        await s.execute(delete(Session).where(Session.id == session_id))
        await s.commit()


async def list_rooms() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Session, func.count(Message.id))
            .outerjoin(Message, Message.session_id == Session.id)
            .group_by(Session.id)
            .order_by(Session.created_at.desc())
        )
        # 예약 작업이 붙은 세션은 뱃지용으로 표시
        job_sids = {
            sid for (sid,) in (
                await s.execute(select(ScheduledJob.session_id).where(ScheduledJob.session_id != ""))
            ).all()
        }
        return [
            {
                "id": sess.id,
                "title": sess.title,
                "workspace_path": sess.workspace_path,
                "workspace_locked": sess.workspace_locked,
                "mode": sess.mode,
                "count": count,
                "used_tokens": sess.used_tokens,
                "logical_budget": sess.logical_budget,
                "running": sess.running,
                "final_status": sess.final_status,
                "scheduled": sess.id in job_sids,
                "auto_approve": sess.auto_approve,
                # 모델 티어는 세션별 설정이다 — 프론트가 방 전환 시 이 값으로 복원한다
                # (전역 localStorage 하나만 쓰면 다른 세션의 선택이 그대로 보인다).
                "model_tier": sess.model_tier or "auto",
            }
            for sess, count in result.all()
        ]


async def update_context_usage(session_id: str, used_tokens: int) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.used_tokens = used_tokens
            await s.commit()


async def mark_running(session_id: str, running: bool) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.running = running
            await s.commit()


async def set_session_auto_approve(session_id: str, enabled: bool) -> None:
    """세션의 승인 정책을 영속화한다 — durable resume가 이 값을 복원해 권한 확대를 막는다."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.auto_approve = bool(enabled)
            await s.commit()


async def get_session_auto_approve(session_id: str) -> bool:
    """세션의 승인 정책을 읽는다. 모르면 False(안전 — 자동 승인하지 않음)."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        return bool(sess.auto_approve) if sess else False


async def set_session_model_tier(session_id: str, tier: str) -> None:
    """세션의 모델 티어를 영속화한다 — durable resume가 이 값을 복원해
    재시작 후에도 같은 모델 정책으로 이어간다."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.model_tier = tier if tier in ("auto", "pro", "flash") else "auto"
            await s.commit()


async def get_session_model_tier(session_id: str) -> str:
    """세션의 모델 티어를 읽는다. 모르면 "auto"(기본 정책)."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        return sess.model_tier if sess and sess.model_tier else "auto"


async def set_session_compaction(session_id: str, summary: str, covered: int) -> None:
    """압축 요약을 영속화한다.

    이게 없으면 요약이 메모리에만 남고 `cleanup_session`이 run 종료마다 지운다 —
    다음 run은 요약 없이 전체 히스토리를 다시 보내고, 다시 압축하고, 또 버린다.
    압축이 매 run 안에서만 유효해 누적 효과가 0이 된다(실측: 컨텍스트 120% 세션).
    """
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.compact_summary = summary or ""
            sess.compact_covered = max(0, int(covered or 0))
            await s.commit()


async def get_session_compaction(session_id: str) -> dict | None:
    """영속화된 압축 요약을 읽는다. 없으면 None."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess and sess.compact_summary and sess.compact_covered > 0:
            return {"summary": sess.compact_summary, "covered": sess.compact_covered}
        return None


async def reconcile_interrupted_runs() -> int:
    """서버 시작 시, running=True로 남은 세션은 재시작으로 중단된 run이다.
    복구 안내 메시지를 히스토리에 남기고 플래그를 내린다. 정리한 세션 수를 반환."""
    async with async_session() as s:
        result = await s.execute(select(Session).where(Session.running == True))  # noqa: E712
        stuck = result.scalars().all()
        ids = [sess.id for sess in stuck]
        for sess in stuck:
            sess.running = False
        await s.commit()
    note = {
        "role": "assistant",
        "content": "서버가 재시작되어 진행 중이던 작업이 중단되었습니다. 필요하면 다시 요청해주세요.",
    }
    for sid in ids:
        history = await load_history(sid)
        if history and history[-1].get("role") == "user":
            history.append(note)
            await save_history(sid, history)
    return len(ids)


async def take_interrupted_runs() -> list[dict]:
    """재시작으로 중단된(running=True) 세션을 찾아 running=False로 내리고 목록을 반환한다.
    재개할지(auto-resume) 안내 메시지만 남길지는 호출측이 final_status로 판단한다.
    각 항목: {id, final_status, workspace_path}."""
    async with async_session() as s:
        result = await s.execute(select(Session).where(Session.running == True))  # noqa: E712
        stuck = result.scalars().all()
        out = [{"id": x.id, "final_status": x.final_status or "",
                "workspace_path": x.workspace_path} for x in stuck]
        for x in stuck:
            x.running = False
        await s.commit()
    return out


async def mark_interrupted_note(session_id: str) -> None:
    """재개하지 않는 중단 세션에 안내 메시지를 남긴다(마지막이 user 턴일 때만)."""
    history = await load_history(session_id)
    if history and history[-1].get("role") == "user":
        history.append({"role": "assistant",
                        "content": "서버가 재시작되어 진행 중이던 작업이 중단되었습니다. 필요하면 다시 요청해주세요."})
        await save_history(session_id, history)
