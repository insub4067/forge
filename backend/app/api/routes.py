import asyncio
import json
import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..db import store
from ..runtime.agent import AgentRuntime

router = APIRouter()
runtime = AgentRuntime()


@router.post("/chat")
async def chat(req: Request):
    body = await req.json()
    session_id = body.get("session_id") or uuid.uuid4().hex
    message = str(body.get("message", ""))

    history = await store.load_history(session_id)
    if not history:
        await store.ensure_session(session_id, message[:40])
    history.append({"role": "user", "content": message})

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(evt: dict) -> None:
        await queue.put(evt)

    async def run_and_close() -> None:
        try:
            new_history = await runtime.run(history, emit)
            await store.save_history(session_id, new_history)
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
    return await store.list_sessions()


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    return await store.load_history(session_id)
