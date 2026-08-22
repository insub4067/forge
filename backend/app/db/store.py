import json
import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from .models import AgentRun, Checkpoint, Message, Session, Task, VisionAnalysis
from .session import async_session


async def ensure_session(
    session_id: str, title: str = "", workspace_path: str | None = None
) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess is None:
            s.add(
                Session(
                    id=session_id,
                    title=title or "새 세션",
                    workspace_path=workspace_path,
                )
            )
        else:
            if title and not sess.title:
                sess.title = title
            if workspace_path and sess.workspace_path != workspace_path:
                sess.workspace_path = workspace_path
        await s.commit()


async def create_room(name: str, workspace_path: str = "") -> str:
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


async def update_room_title(session_id: str, title: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.title = title
            await s.commit()


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
        }


async def delete_room(session_id: str) -> None:
    async with async_session() as s:
        await s.execute(delete(Message).where(Message.session_id == session_id))
        await s.execute(delete(Task).where(Task.session_id == session_id))
        await s.execute(delete(Checkpoint).where(Checkpoint.session_id == session_id))
        await s.execute(delete(Session).where(Session.id == session_id))
        await s.commit()


async def load_history(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.seq)
        )
        return [json.loads(m.content_json) for m in result.scalars()]


async def save_history(session_id: str, history: list[dict]) -> None:
    async with async_session() as s:
        await s.execute(delete(Message).where(Message.session_id == session_id))
        for i, msg in enumerate(history):
            s.add(
                Message(
                    session_id=session_id,
                    seq=i,
                    role=msg.get("role", ""),
                    content_json=json.dumps(msg, ensure_ascii=False),
                )
            )
        await s.commit()


async def list_rooms() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Session, func.count(Message.id))
            .outerjoin(Message, Message.session_id == Session.id)
            .group_by(Session.id)
            .order_by(Session.created_at.desc())
        )
        return [
            {
                "id": sess.id,
                "title": sess.title,
                "workspace_path": sess.workspace_path,
                "workspace_locked": sess.workspace_locked,
                "count": count,
                "used_tokens": sess.used_tokens,
                "logical_budget": sess.logical_budget,
            }
            for sess, count in result.all()
        ]


async def update_context_usage(session_id: str, used_tokens: int) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.used_tokens = used_tokens
            await s.commit()


async def save_checkpoint(session_id: str, step_no: int, git_sha: str) -> None:
    async with async_session() as s:
        s.add(Checkpoint(session_id=session_id, step_no=step_no, git_sha=git_sha))
        await s.commit()


async def replace_tasks(session_id: str, tasks: list[dict]) -> None:
    async with async_session() as s:
        await s.execute(delete(Task).where(Task.session_id == session_id))
        for t in tasks:
            s.add(
                Task(
                    session_id=session_id,
                    title=str(t.get("title", "")),
                    status=str(t.get("status", "todo")),
                    progress=int(t.get("progress", 0)),
                )
            )
        await s.commit()


async def list_tasks(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )
        return [
            {"id": t.id, "title": t.title, "status": t.status, "progress": t.progress}
            for t in result.scalars()
        ]


async def save_agent_run(
    session_id: str,
    role: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    thinking_enabled: bool = False,
    reasoning_effort: str = "",
) -> None:
    async with async_session() as s:
        s.add(
            AgentRun(
                session_id=session_id,
                role=role,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                thinking_enabled=thinking_enabled,
                reasoning_effort=reasoning_effort,
            )
        )
        await s.commit()


async def save_vision_analysis(
    session_id: str,
    task_id: str,
    analysis_result: str,
    image_path: str = "",
    issues: str = "",
) -> None:
    async with async_session() as s:
        s.add(
            VisionAnalysis(
                session_id=session_id,
                task_id=task_id,
                image_path=image_path,
                analysis_result=analysis_result,
                issues=issues,
            )
        )
        await s.commit()


async def session_agent_runs(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at.desc())
        )
        return [
            {
                "role": r.role,
                "model": r.model,
                "thinking_enabled": r.thinking_enabled,
                "reasoning_effort": r.reasoning_effort,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in result.scalars()
        ]


async def admin_stats(days: int = 7) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    async with async_session() as s:
        result = await s.execute(select(AgentRun).where(AgentRun.created_at >= since))
        runs = result.scalars().all()

        total_prompt = sum(r.prompt_tokens for r in runs)
        total_completion = sum(r.completion_tokens for r in runs)

        role_counts: dict[str, int] = {}
        role_tokens: dict[str, int] = {}
        for r in runs:
            role_counts[r.role] = role_counts.get(r.role, 0) + 1
            role_tokens[r.role] = role_tokens.get(r.role, 0) + r.prompt_tokens + r.completion_tokens

        total_runs = len(runs)
        roles = [
            {
                "role": role,
                "count": count,
                "percent": round(count / total_runs * 100, 1) if total_runs else 0,
                "tokens": role_tokens.get(role, 0),
            }
            for role, count in sorted(role_counts.items(), key=lambda x: -x[1])
        ]

        room_counts: dict[str, int] = {}
        for r in runs:
            room_counts[r.session_id] = room_counts.get(r.session_id, 0) + 1
        rooms = [
            {"session_id": sid, "count": c}
            for sid, c in sorted(room_counts.items(), key=lambda x: -x[1])
        ]

        return {
            "days": days,
            "total_runs": total_runs,
            "total_tokens": total_prompt + total_completion,
            "total_prompt": total_prompt,
            "total_completion": total_completion,
            "roles": roles,
            "rooms": rooms,
        }
