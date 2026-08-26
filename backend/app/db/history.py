"""히스토리 저장·검색 — store.py에서 분리한 도메인 모듈."""
import json

from sqlalchemy import delete, select

from .models import Message, Session
from .session import async_session


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
        # 실행 중 세션이 삭제되면 뒤늦은 저장이 FK 위반으로 크래시한다 → 세션 없으면 skip.
        if await s.get(Session, session_id) is None:
            return
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


async def search_messages(query: str, limit: int = 30) -> list[dict]:
    """메시지 내용에서 query를 검색해 세션별 첫 매칭 스니펫을 반환한다."""
    q = query.strip()
    if not q:
        return []
    async with async_session() as s:
        result = await s.execute(
            select(Message.session_id, Message.role, Message.content_json)
            .where(Message.content_json.ilike(f"%{q}%"))
            .order_by(Message.session_id, Message.seq)
            .limit(300)
        )
        seen: dict[str, dict] = {}
        for sid, role, cj in result.all():
            if sid in seen:
                continue
            try:
                content = json.loads(cj).get("content", "")
            except Exception:
                content = cj
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
                )
            text = str(content)
            idx = text.lower().find(q.lower())
            start = max(0, idx - 30)
            snippet = ("…" if start > 0 else "") + text[start:start + 100].strip()
            seen[sid] = {"session_id": sid, "role": role, "snippet": snippet}
            if len(seen) >= limit:
                break
        return list(seen.values())
