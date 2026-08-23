import asyncio
import json
import os
import re
import subprocess
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, Response
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..db import store
from .. import errors as error_log
from .. import metrics as metrics_calc
from .. import skills as skills_lib
from ..runtime.agent import AgentRuntime
from ..tools.registry import _resolve

router = APIRouter()
runtime = AgentRuntime()

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


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
async def fs_list(path: str = "", show_hidden: bool = False, session_id: str = ""):
    # 세션이 지정되면 해당 방의 워크스페이스 안으로만 탐색을 제한한다.
    if session_id:
        ws = await _room_workspace(session_id)
        try:
            target = str(_resolve(ws, path)) if path else ws
        except PermissionError:
            target = ws
    else:
        target = os.path.expanduser(path) if path else os.path.expanduser("~")
    if not os.path.isdir(target):
        target = ws if session_id else os.path.expanduser("~")
    entries = []
    try:
        names = sorted(os.listdir(target))
    except OSError:
        names = []
    for name in names:
        full = os.path.join(target, name)
        if not show_hidden and name.startswith("."):
            continue
        is_dir = os.path.isdir(full)
        entries.append({"name": name, "path": full, "is_dir": is_dir})
    parent = os.path.dirname(target) if target != "/" else None
    return {"path": target, "parent": parent, "entries": entries}


@router.get("/fs/read")
async def fs_read(path: str = "", session_id: str = ""):
    if session_id:
        ws = await _room_workspace(session_id)
        if not path:
            return {"path": "", "content": "파일이 아닙니다."}
        try:
            p = str(_resolve(ws, path))
        except PermissionError:
            return {"path": path, "content": "작업 영역 밖 파일은 열 수 없습니다."}
    else:
        p = os.path.expanduser(path) if path else ""
    if not p or not os.path.isfile(p):
        return {"path": p, "content": "파일이 아닙니다."}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": p, "content": content[:50_000]}
    except Exception as err:
        return {"path": p, "content": f"오류: {err}"}


@router.get("/fs/raw")
async def fs_raw(path: str = "", session_id: str = ""):
    """워크스페이스 내 파일 원본 서빙(이미지/영상/PDF 미리보기용). 경계 밖은 차단."""
    if session_id:
        ws = await _room_workspace(session_id)
        try:
            p = str(_resolve(ws, path))
        except PermissionError:
            return Response(status_code=403)
    else:
        p = os.path.expanduser(path) if path else ""
    if not p or not os.path.isfile(p):
        return Response(status_code=404)
    return FileResponse(p)


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        ext = ".png"
    name = uuid.uuid4().hex + ext
    content = await file.read()
    (UPLOADS_DIR / name).write_bytes(content)
    return {"url": f"/uploads/{name}", "name": name}


async def _notify_done(session_id: str, history: list) -> None:
    """작업 완료 시 등록된 기기에 Web Push. 실패는 무시(발송 루프 보호)."""
    from .. import push
    subs = await store.all_subscriptions()
    if not subs:
        return
    room = await store.get_room(session_id)
    title = (room.get("title") if room else "") or "작업 완료"
    body = "FORGE 작업이 끝났습니다."
    for msg in reversed(history):
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), str) and msg["content"].strip():
            body = msg["content"].strip()[:120]
            break
    for sub in subs:
        push.send_one(sub, f"✓ {title[:40]}", body, "/")


@router.post("/chat")
async def chat(req: Request):
    body = await req.json()
    session_id = body.get("session_id") or uuid.uuid4().hex
    message = str(body.get("message", ""))
    runtime.set_auto_approve(session_id, bool(body.get("auto_approve", False)))
    runtime.set_model_tier(session_id, str(body.get("model_tier", "auto")))
    runtime.set_agent_mode(session_id, str(body.get("agent_mode", "auto")))

    # 이미 실행 중인 세션이면 새 run을 띄우지 않고 기존 run에 주입한다 —
    # 같은 세션에 run이 겹쳐 돌며 상태를 밟아 멈추는 것을 방지(동시 run 레이스).
    if body.get("session_id") and not runtime.try_begin(session_id):
        runtime.inject(session_id, message)

        async def queued_gen():
            yield {"event": "user_injected",
                   "data": json.dumps({"type": "user_injected", "data": {"content": message}}, ensure_ascii=False)}
            yield {"event": "done",
                   "data": json.dumps({"type": "done", "data": {
                       "status": "queued",
                       "content": "이미 실행 중인 작업에 메시지를 추가했습니다."}}, ensure_ascii=False)}

        return EventSourceResponse(queued_gen(), headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    room = await store.get_room(session_id)
    workspace_path = room["workspace_path"] if room else None

    history = await store.load_history(session_id)
    if not history:
        await store.ensure_session(session_id, message[:40], workspace_path)

    # 다중 이미지 지원(image_urls). 단일 image_url도 하위호환.
    image_urls = body.get("image_urls") or ([body["image_url"]] if body.get("image_url") else [])
    if image_urls:
        content = [{"type": "text", "text": message}] + [
            {"type": "image_url", "image_url": {"url": u}} for u in image_urls
        ]
    else:
        content = message
    history.append({"role": "user", "content": content})
    # 사용자 메시지를 즉시 저장한다 — run이 크래시하거나 앱을 중간에 꺼도
    # 사용자 턴이 유실되지 않도록.
    await store.save_history(session_id, history)

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(evt: dict) -> None:
        await queue.put(evt)

    # run 진행을 DB에 표시 — 서버 재시작으로 중단되면 시작 시 감지·정리된다.
    await store.mark_running(session_id, True)

    async def run_and_close() -> None:
        try:
            new_history = await runtime.run(history, emit, session_id, workspace_path)
            await store.save_history(session_id, new_history)
            await _notify_done(session_id, new_history)
        except Exception as err:
            error_log.record("agent_run", str(err), session_id)
            # 크래시해도 응답이 조용히 사라지지 않게 오류 메시지를 히스토리에 남긴다.
            history.append({
                "role": "assistant",
                "content": f"작업 중 오류가 발생해 중단했습니다: {str(err)[:300]}",
            })
            await store.save_history(session_id, history)
            await queue.put(
                {"seq": 0, "type": "error", "data": {"message": str(err)}}
            )
        finally:
            await store.mark_running(session_id, False)
            runtime.cleanup_session(session_id)
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

    return EventSourceResponse(gen(), headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.post("/rooms")
async def create_room(req: Request):
    body = await req.json()
    name = str(body.get("name", "")).strip() or "Forge"
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


@router.get("/search")
async def search(q: str = ""):
    return {"results": await store.search_messages(q)}


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    history = await store.load_history(session_id)
    # 히스토리가 비었으면 컨텍스트 사용량도 0으로 자가 치유
    # (과거 크래시로 대화는 사라지고 used_tokens만 남은 유령 상태 정리)
    if not history:
        await store.update_context_usage(session_id, 0)
    return history


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


@router.get("/sessions/{session_id}/running")
async def session_running(session_id: str):
    return {"running": runtime.is_running(session_id)}


@router.get("/sessions/{session_id}/status")
async def session_status(session_id: str):
    """에이전트 라이브 상태 — 스트림이 끊겨도 언제나 조회 가능.
    running / role / last_event / idle_seconds / waiting_for(승인·질문) / pending."""
    return runtime.get_status(session_id)


@router.get("/admin/action-log")
async def action_log(session_id: str = "", limit: int = 200):
    from .. import eventlog
    return {"events": eventlog.tail(session_id, limit)}


@router.get("/push/vapid-public")
async def push_vapid_public():
    return {"public_key": settings.vapid_public_key}


def _parse_dt(v):
    """ISO 문자열(±tz) → naive UTC datetime."""
    from datetime import datetime, timezone as _tz
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone(_tz.utc).replace(tzinfo=None)
        return d
    except Exception:
        return None


@router.get("/jobs")
async def jobs_list():
    return {"jobs": await store.list_jobs()}


@router.post("/jobs")
async def jobs_create(req: Request):
    body = await req.json()
    # 워크스페이스 미지정 시 전용 폴더 자동 생성 — 기존 프로젝트(forge 등)에 섞이지 않게.
    workspace = str(body.get("workspace_path", "")).strip()
    if not workspace:
        safe = re.sub(r"[^\w가-힣.-]", "_", str(body.get("name", "job")))[:30] or "job"
        workspace = str(Path.home() / "forge-jobs" / f"{safe}-{uuid.uuid4().hex[:6]}")
        try:
            Path(workspace).mkdir(parents=True, exist_ok=True)
        except Exception:
            workspace = str(Path.home() / "forge-jobs")
            Path(workspace).mkdir(parents=True, exist_ok=True)
    data = {
        "name": str(body.get("name", "")),
        "prompt": str(body.get("prompt", "")),
        "workspace_path": workspace,
        "session_id": str(body.get("session_id", "")),
        "timezone": str(body.get("timezone", "Asia/Seoul")),
        "next_run_at": _parse_dt(body.get("next_run_at")),
        "recurrence": str(body.get("recurrence", "")),
        "recurrence_value": str(body.get("recurrence_value", "")),
        "auto_approve": bool(body.get("auto_approve", True)),
    }
    return await store.create_job(data)


@router.patch("/jobs/{job_id}")
async def jobs_update(job_id: int, req: Request):
    body = await req.json()
    fields = {}
    if "enabled" in body:
        fields["enabled"] = bool(body["enabled"])
    if "next_run_at" in body:
        fields["next_run_at"] = _parse_dt(body["next_run_at"])
    await store.update_job(job_id, fields)
    return {"ok": True}


@router.delete("/jobs/{job_id}")
async def jobs_delete(job_id: int):
    await store.delete_job(job_id)
    return {"deleted": True}


@router.post("/jobs/{job_id}/run")
async def jobs_run_now(job_id: int):
    job = await store.get_job(job_id)
    if not job:
        return {"error": "not found"}
    from .. import scheduler
    asyncio.create_task(scheduler.run_job(job))
    return {"started": True}


# 재시작으로 자식이 고아가 돼도 켜고 끌 수 있게 pgrep/pkill로 상태를 판정한다.
_CAFFEINATE_MARK = "caffeinate -dimsu"


async def _caffeinate_running() -> bool:
    proc = await asyncio.create_subprocess_exec(
        "pgrep", "-f", _CAFFEINATE_MARK,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait() == 0


@router.get("/mac/caffeinate")
async def caffeinate_status():
    if sys.platform != "darwin":
        return {"on": False}
    return {"on": await _caffeinate_running()}


@router.post("/mac/caffeinate")
async def caffeinate_toggle(req: Request):
    """맥 절전 방지 토글 — caffeinate 프로세스를 켜고/끈다."""
    if sys.platform != "darwin":
        return {"on": False, "error": "unsupported"}
    on = bool((await req.json()).get("on"))
    running = await _caffeinate_running()
    if on and not running:
        # -d 디스플레이, -i 유휴, -m 디스크, -s 시스템, -u 사용자활성
        await asyncio.create_subprocess_exec("caffeinate", "-dimsu")
    elif not on and running:
        killer = await asyncio.create_subprocess_exec("pkill", "-f", _CAFFEINATE_MARK)
        await killer.wait()
    return {"on": on}


@router.get("/mac/camera")
async def camera_frame(max_px: int = 960):
    """맥 웹캠 단일 프레임 — imagesnap으로 캡처('카메라' 권한 필요).

    imagesnap이 필요하다: `brew install imagesnap`. avfoundation(ffmpeg)은
    이 맥에서 프레임을 안정적으로 내보내지 못해 전용 CLI를 쓴다.
    """
    if sys.platform != "darwin":
        return Response(content=b"unsupported", status_code=501)
    if not shutil.which("imagesnap"):
        return Response(content="imagesnap 미설치: brew install imagesnap".encode(), status_code=501)
    tmp = Path(tempfile.gettempdir()) / "forge_cam.jpg"
    try:
        # -w: 웜업(자동 노출), -q: 조용히. 단일 프레임을 파일로.
        proc = await asyncio.create_subprocess_exec(
            "imagesnap", "-w", "0.4", "-q", str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=8)
        if not tmp.exists() or tmp.stat().st_size == 0:
            msg = stderr.decode(errors="ignore").strip() or "capture failed"
            return Response(content=f"카메라 권한 필요: {msg}".encode(), status_code=403)
        resize = await asyncio.create_subprocess_exec(
            "sips", "-Z", str(max_px), str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await resize.wait()
        return Response(
            content=tmp.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as err:
        return Response(content=str(err).encode(), status_code=500)


@router.websocket("/terminals/ws")
async def terminal_ws(ws: WebSocket, session_id: str = "", cols: int = 80, rows: int = 24):
    """host PTY 터미널 — 방의 워크스페이스에서 인터랙티브 셸을 연다."""
    await ws.accept()
    if sys.platform != "darwin":
        await ws.send_text("터미널은 macOS host에서만 지원됩니다.\r\n")
        await ws.close()
        return
    from .. import terminal
    room = await store.get_room(session_id) if session_id else None
    workspace = (room.get("workspace_path") if room else "") or settings.workspace
    await terminal.bridge(ws, workspace, cols=cols, rows=rows)


@router.get("/mac/screen")
async def mac_screen(display: int = 1, max_px: int = 1600):
    """macOS 화면 캡처(view-only). '화면 기록' 권한이 필요하다."""
    if sys.platform != "darwin":
        return Response(content=b"unsupported", status_code=501)
    tmp = Path(tempfile.gettempdir()) / "forge_screen.jpg"
    try:
        args = ["screencapture", "-x", "-t", "jpg"]
        if display > 1:
            args += ["-D", str(display)]  # 보조 디스플레이만 지정, 기본은 주화면
        args.append(str(tmp))
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=8)
        if not tmp.exists():
            msg = stderr.decode(errors="ignore").strip() or "capture failed"
            # 화면 기록 권한 미허용 시 macOS가 이 에러를 반환한다.
            return Response(content=f"화면 기록 권한 필요: {msg}".encode(), status_code=403)
        # 대역폭 절감: 긴 변 max_px로 축소
        resize = await asyncio.create_subprocess_exec(
            "sips", "-Z", str(max_px), str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await resize.wait()
        return Response(
            content=tmp.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as err:
        return Response(content=str(err).encode(), status_code=500)


@router.post("/push/subscribe")
async def push_subscribe(req: Request):
    body = await req.json()
    sub = body.get("subscription") or {}
    endpoint = sub.get("endpoint", "")
    if not endpoint:
        return {"ok": False, "error": "no endpoint"}
    await store.register_device(str(body.get("name", "")), endpoint, json.dumps(sub, ensure_ascii=False))
    return {"ok": True}


@router.get("/push/devices")
async def push_devices():
    return {"devices": await store.list_devices()}


@router.delete("/push/devices/{device_id}")
async def push_device_delete(device_id: int):
    await store.delete_device(device_id)
    return {"deleted": True}


@router.post("/push/test")
async def push_test():
    from .. import push
    subs = await store.all_subscriptions()
    sent = sum(1 for s in subs if push.send_one(s, "FORGE", "테스트 알림입니다.", "/"))
    return {"sent": sent, "total": len(subs)}


@router.post("/sessions/{session_id}/auto-approve")
async def set_auto_approve(session_id: str, req: Request):
    body = await req.json()
    enabled = bool(body.get("enabled", False))
    runtime.set_auto_approve(session_id, enabled)
    resolved = runtime.resolve_pending_approvals(session_id) if enabled else 0
    return {"enabled": enabled, "resolved": resolved}


@router.post("/sessions/{session_id}/inject")
async def inject_message(session_id: str, req: Request):
    body = await req.json()
    text = str(body.get("text", ""))
    running = runtime.is_running(session_id)
    injected = runtime.inject(session_id, text) if running else False
    return {"injected": injected, "running": running}


@router.get("/rooms/{session_id}/git/status")
async def git_status(session_id: str):
    ws = await _room_workspace(session_id)
    return {"output": _git(ws, "-c", "core.quotepath=false", "status", "--short")}


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


_SEP = "\x1f"


@router.get("/rooms/{session_id}/git/log")
async def git_log(session_id: str, limit: int = 50, skip: int = 0):
    ws = await _room_workspace(session_id)
    limit = max(1, min(limit, 200))
    skip = max(0, skip)
    raw = _git(
        ws, "-c", "core.quotepath=false", "log", "--skip", str(skip), "-n", str(limit),
        f"--pretty=format:%h{_SEP}%s{_SEP}%an{_SEP}%ar",
    )
    commits = []
    for line in raw.splitlines():
        parts = line.split(_SEP)
        if len(parts) == 4:
            commits.append(
                {"hash": parts[0], "subject": parts[1], "author": parts[2], "date": parts[3]}
            )
    return {"commits": commits, "has_more": len(commits) == limit}


@router.get("/rooms/{session_id}/git/file-diff")
async def git_file_diff(session_id: str, path: str = ""):
    ws = await _room_workspace(session_id)
    if not path:
        return {"diff": ""}
    out = _git(ws, "-c", "core.quotepath=false", "diff", "--", path)
    if not out.strip():
        # 추적되지 않은 새 파일 — 전체를 추가로 표시
        out = _git(ws, "-c", "core.quotepath=false", "diff", "--no-index", "--", "/dev/null", path)
    return {"diff": out}


@router.get("/rooms/{session_id}/git/commit")
async def git_commit(session_id: str, hash: str = ""):
    ws = await _room_workspace(session_id)
    if not re.fullmatch(r"[0-9a-fA-F]{4,40}", hash or ""):
        return {"error": "잘못된 커밋 해시입니다."}
    meta = _git(
        ws, "-c", "core.quotepath=false", "show", "-s",
        f"--pretty=format:%h{_SEP}%an{_SEP}%ar{_SEP}%s", hash,
    ).split(_SEP)
    diff = _git(ws, "-c", "core.quotepath=false", "show", "--format=", hash)
    if len(meta) == 4:
        return {"hash": meta[0], "author": meta[1], "date": meta[2], "subject": meta[3], "diff": diff}
    return {"hash": hash, "author": "", "date": "", "subject": "", "diff": diff}


@router.get("/admin/stats")
async def admin_stats():
    stats = await store.admin_stats(7)
    stats["provider"] = settings.llm_provider
    stats["policy"] = runtime.router.get_policy()
    return stats


@router.get("/admin/errors")
async def admin_errors():
    return {"errors": error_log.recent()}


@router.get("/admin/model-policy")
async def get_model_policy():
    return runtime.router.get_policy()


@router.get("/admin/balance")
async def admin_balance():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {settings.deep_seek_api_key}"},
            )
            if r.status_code == 200:
                return r.json()
            return {"error": f"HTTP {r.status_code}"}
    except Exception as err:
        return {"error": str(err)}


@router.put("/admin/model-policy/{role}")
async def update_model_policy(role: str, req: Request):
    body = await req.json()
    ok = runtime.router.update_policy(
        role,
        model=body.get("model"),
        thinking=body.get("thinking"),
        reasoning_effort=body.get("reasoning_effort"),
    )
    return {"ok": ok}


@router.get("/rooms/{session_id}/skills")
async def list_skills(session_id: str):
    ws = await _room_workspace(session_id)
    # global + workspace 병합(같은 이름은 workspace 우선), 각 항목에 scope 포함.
    return {"skills": skills_lib.iter_skills(ws)}


@router.delete("/rooms/{session_id}/skills/{name}")
async def delete_skill(session_id: str, name: str, scope: str = "project"):
    ws = await _room_workspace(session_id)
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()
    scope = "global" if scope == "global" else "project"
    try:
        p = skills_lib.resolve_path(scope, ws, name, safe)
    except PermissionError:
        return {"deleted": False}
    if p.is_file():
        p.unlink()
        return {"deleted": True}
    return {"deleted": False}


@router.get("/rooms/{session_id}/runs")
async def room_runs(session_id: str):
    return await store.session_agent_runs(session_id)


@router.get("/metrics/summary")
async def metrics_summary():
    """전체 세션의 성공률·토큰·캐시·비용 집계 + 병목 진단."""
    agg = await store.metrics_summary()
    runs = await store.all_runs_for_cost()
    cost, priced, total = metrics_calc.sum_cost(runs)
    agg["estimated_cost"] = cost
    agg["priced_runs"] = priced
    agg["total_runs"] = total
    if total:
        agg["cost_per_success"] = round(cost / agg["successful"], 6) if agg.get("successful") else None
    agg["bottlenecks"] = metrics_calc.bottlenecks(agg)
    return agg


@router.get("/rooms/{session_id}/metrics")
async def room_metrics(session_id: str):
    """세션 하나의 비용 집계 + role 실행 상세 + 비용."""
    agg = await store.session_metrics(session_id)
    runs = await store.session_agent_runs(session_id)
    cost, priced, total = metrics_calc.sum_cost(runs)
    agg["estimated_cost"] = cost
    agg["runs"] = runs
    agg["bottlenecks"] = metrics_calc.bottlenecks(agg)
    return agg
