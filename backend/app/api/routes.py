import asyncio
import json
import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..runtime.agent import AgentRuntime

router = APIRouter()
runtime = AgentRuntime()

SESSIONS: dict[str, dict] = {}


def _get_session(session_id: str) -> dict:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"title": "", "messages": []}
    return SESSIONS[session_id]


@router.post("/chat")
async def chat(req: Request):
    body = await req.json()
    session_id = body.get("session_id") or uuid.uuid4().hex
    message = str(body.get("message", ""))

    session = _get_session(session_id)
    if not session["title"]:
        session["title"] = message[:40]
    session["messages"].append({"role": "user", "content": message})

    history = session["messages"]
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(evt: dict) -> None:
        await queue.put(evt)

    async def run_and_close() -> None:
        try:
            new_history = await runtime.run(history, emit)
            session["messages"] = new_history
        except Exception as err:
            await queue.put(
                {"seq": 0, "type": "error", "data": {"message": str(err)}}
            )
        finally:
            await queue.put(None)

    asyncio.create_task(run_and_close())

    async def gen():
        while True:
            evt = await queue.get()
            if evt is None:
                break
            yield {
                "event": evt["type"],
                "data": json.dumps(evt, ensure_ascii=False),
            }

    return EventSourceResponse(gen())


@router.get("/sessions")
async def list_sessions():
    return [
        {"id": sid, "title": s["title"], "count": len(s["messages"])}
        for sid, s in SESSIONS.items()
    ]


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    session = SESSIONS.get(session_id)
    return session["messages"] if session else []
