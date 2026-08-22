import json

from sqlalchemy import delete, func, select

from .models import Message, Session
from .session import async_session


async def ensure_session(session_id: str, title: str = "") -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess is None:
            s.add(Session(id=session_id, title=title or "새 세션"))
        elif title and not sess.title:
            sess.title = title
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


async def list_sessions() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Session, func.count(Message.id))
            .outerjoin(Message, Message.session_id == Session.id)
            .group_by(Session.id)
            .order_by(Session.created_at.desc())
        )
        return [
            {"id": sess.id, "title": sess.title, "count": count}
            for sess, count in result.all()
        ]
