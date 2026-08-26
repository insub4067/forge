from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings
from .models import Session

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session



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
