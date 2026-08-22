import asyncio
import json
import os
import subprocess
import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..db import store
from ..runtime.agent import AgentRuntime

router = APIRouter()
runtime = AgentRuntime()


def _git(workspace: str, *args: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", workspace, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (r.stdout + r.stderr).strip()
    except Exception as err:
        return f"오류: {err}"


async def _room_workspace(session_id: str) -> str:
    room = await store.get_room(session_id)
    return room["workspace_path"] if room and room["workspace_path"] else settings.workspace


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
        if name.startswith("."):
            continue
        is_dir = os.path.isdir(full)
        entries.append({"name": name, "path": full, "is_dir": is_dir})
    parent = os.path.dirname(target) if target != "/" else None
    return {"path": target, "parent": parent, "entries": entries}


@router.get("/fs/read")
async def fs_read(path: str = ""):
    p = os.path.expanduser(path) if path else ""
    if not p or not os.path.isfile(p):
        return {"path": p, "content": "파일이 아닙니다."}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": p, "content": content[:50_000]}
    except Exception as err:
        return {"path": p, "content": f"오류: {err}"}


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
    title = str(body.get("title", "")).strip()
    workspace_path = str(body.get("workspace_path", "")).strip()
    if title:
        await store.update_room_title(session_id, title)
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


@router.get("/rooms/{session_id}/git/status")
async def git_status(session_id: str):
    ws = await _room_workspace(session_id)
    return {"output": _git(ws, "status", "--short")}


@router.get("/rooms/{session_id}/git/branches")
async def git_branches(session_id: str):
    ws = await _room_workspace(session_id)
    current = _git(ws, "branch", "--show-current")
    raw = _git(ws, "branch")
    branches = [b.lstrip("* ").strip() for b in raw.splitlines() if b.strip()]
    return {"current": current, "branches": branches}


@router.post("/rooms/{session_id}/git/checkout")
async def git_checkout(session_id: str, req: Request):
    ws = await _room_workspace(session_id)
    body = await req.json()
    branch = str(body.get("branch", "")).strip()
    if not branch:
        return {"output": "브랜치를 지정하세요."}
    return {"output": _git(ws, "checkout", branch)}


@router.get("/rooms/{session_id}/git/diff")
async def git_diff(session_id: str):
    ws = await _room_workspace(session_id)
    return {"output": _git(ws, "diff", "--stat")}


@router.get("/admin/stats")
async def admin_stats():
    stats = await store.admin_stats(7)
    stats["provider"] = settings.llm_provider
    stats["models"] = {
        "planner": settings.planner_model or settings.deep_seek_model,
        "coder": settings.coder_model or settings.deep_seek_model,
        "reviewer": settings.reviewer_model or settings.deep_seek_model,
        "debugger": settings.debugger_model or settings.deep_seek_model,
    }
    return stats


@router.get("/rooms/{session_id}/runs")
async def room_runs(session_id: str):
    return await store.session_agent_runs(session_id)
