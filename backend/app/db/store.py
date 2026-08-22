import json
import os
import uuid

from sqlalchemy import delete, func, select

from .models import Checkpoint, Message, Session, Task
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
    if not workspace_path:
        workspace_path = os.path.expanduser("~")
    async with async_session() as s:
        s.add(Session(id=room_id, title=name, workspace_path=workspace_path))
        await s.commit()
    return room_id


async def update_room_workspace(session_id: str, workspace_path: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.workspace_path = workspace_path
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
