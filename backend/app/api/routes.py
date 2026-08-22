import asyncio
import json
import os
import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..db import store
from ..runtime.agent import AgentRuntime

router = APIRouter()
runtime = AgentRuntime()


@router.get("/fs/list")
async def fs_list(path: str = ""):
    target = os.path.expanduser(path) if path else os.path.expanduser("~")
    if not os.path.isdir(target):
        target = os.path.expanduser("~")
    entries = []
    try:
        names = sorted(os.listdir(target))
    except OSError:
        names = []
    for name in names:
        full = os.path.join(target, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue
        entries.append({"name": name, "path": full, "is_dir": True})
    parent = os.path.dirname(target) if target != "/" else None
    return {"path": target, "parent": parent, "entries": entries}


@router.post("/chat")
async def chat(req: Request):
    body = await req.json()
    session_id = body.get("session_id") or uuid.uuid4().hex
    message = str(body.get("message", ""))

    room = await store.get_room(session_id)
    workspace_path = room["workspace_path"] if room else None

    history = await store.load_history(session_id)
    if not history:
        await store.ensure_session(session_id, message[:40], workspace_path)
    history.append({"role": "user", "content": message})

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(evt: dict) -> None:
        await queue.put(evt)

    async def run_and_close() -> None:
        try:
            new_history = await runtime.run(history, emit, session_id, workspace_path)
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


@router.post("/rooms")
async def create_room(req: Request):
    body = await req.json()
    name = str(body.get("name", "")).strip() or "새 방"
    workspace_path = str(body.get("workspace_path", "")).strip()
    room_id = await store.create_room(name, workspace_path)
    return await store.get_room(room_id)


@router.get("/rooms")
async def list_rooms():
    return await store.list_rooms()


@router.get("/rooms/{session_id}")
async def get_room(session_id: str):
    return await store.get_room(session_id)


@router.patch("/rooms/{session_id}")
async def update_room(session_id: str, req: Request):
    body = await req.json()
    workspace_path = str(body.get("workspace_path", "")).strip()
    if workspace_path:
        await store.update_room_workspace(session_id, workspace_path)
    return {"ok": True}


@router.delete("/rooms/{session_id}")
async def delete_room(session_id: str):
    await store.delete_room(session_id)
    return {"deleted": True}


@router.get("/rooms/{session_id}/tasks")
async def get_tasks(session_id: str):
    return await store.list_tasks(session_id)


@router.get("/sessions")
async def list_sessions():
    return await store.list_rooms()


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    return await store.load_history(session_id)


@router.post("/approvals/{approval_id}")
async def resolve_approval(approval_id: str, req: Request):
    body = await req.json()
    decision = str(body.get("decision", "reject"))
    resolved = runtime.resolve_approval(approval_id, decision)
    return {"resolved": resolved, "decision": decision}


@router.post("/questions/{question_id}")
async def answer_question(question_id: str, req: Request):
    body = await req.json()
    answer = str(body.get("answer", ""))
    resolved = runtime.answer_question(question_id, answer)
    return {"resolved": resolved}


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str):
    runtime.cancel(session_id)
    return {"cancelled": True}
