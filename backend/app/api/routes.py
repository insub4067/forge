import asyncio
import json
import os
import re
import subprocess
import shutil
import sys
import tempfile
import time
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
from ..llm.factory import create_adapter
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


async def resume_run(session_id: str, workspace_path: str | None) -> None:
    """중단된 run을 저장된 history에서 이어서 완주한다(headless — SSE 클라이언트 없음).
    스텝별 저장 덕분에 진행이 남아 있고, 검증 게이트·자동커밋이 그대로 적용된다.
    크래시 루프 방지: 시작 시 final_status='resuming'으로 표시(재개 중 또 죽으면 재재개 안 함)."""
    try:
        history = await store.load_history(session_id)
        if not history:
            return
        await store.set_session_final_status(session_id, "resuming")
        await store.mark_running(session_id, True)
        # 승인 정책은 재시작 전 사용자가 정한 값을 그대로 복원한다 — 재시작했다는 이유로
        # 권한이 확대되지 않는다(invariant). 원래 auto_approve였으면(무인 위임) 계속 자동 승인,
        # 아니었으면 새 위험 작업은 approval_request로 pause되어 사용자 승인을 기다린다.
        restored_aa = await store.get_session_auto_approve(session_id)
        runtime.set_auto_approve(session_id, restored_aa)

        async def _noop(_evt: dict) -> None:
            return None

        # 재개 상한(defense-in-depth): 폭주하는 재개가 무한히 돌지 않게 20분 타임아웃.
        new_history = await asyncio.wait_for(
            runtime.run(history, _noop, session_id, workspace_path), timeout=1200)
        await store.save_history(session_id, new_history)
        await _notify_done(session_id, new_history)
    except Exception as err:
        error_log.record("resume_run", str(err), session_id)
    finally:
        await store.mark_running(session_id, False)
        runtime.cleanup_session(session_id)


@router.post("/chat")
async def chat(req: Request):
    body = await req.json()
    session_id = body.get("session_id") or uuid.uuid4().hex
    message = str(body.get("message", ""))
    _auto_approve = bool(body.get("auto_approve", False))
    runtime.set_auto_approve(session_id, _auto_approve)
    runtime.set_model_tier(session_id, str(body.get("model_tier", "auto")))
    # 폴링 시작점: 이번 run 이전까지 기록된 마지막 seq. run마다 seq를 새로 세지 않고
    # 세션 단위로 단조 증가시키므로, 이 값부터 새 이벤트를 안전하게 이어 받는다.
    from .. import eventlog
    _prev = eventlog.tail(session_id, limit=1)
    _base_seq = _prev[0]["seq"] if _prev else 0
    _sse_headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "X-Last-Seq": str(_base_seq),
    }

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

        return EventSourceResponse(queued_gen(), headers=_sse_headers)

    room = await store.get_room(session_id)
    workspace_path = room["workspace_path"] if room else None

    history = await store.load_history(session_id)
    if not history:
        await store.ensure_session(session_id, message[:40], workspace_path)
    # 승인 정책 영속화 — durable resume가 이 값을 복원해 권한이 확대되지 않게 한다.
    await store.set_session_auto_approve(session_id, _auto_approve)

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

    return EventSourceResponse(gen(), headers=_sse_headers)


@router.post("/rooms")
async def create_room(req: Request):
    body = await req.json()
    name = str(body.get("name", "")).strip() or "Forge"
    workspace_path = str(body.get("workspace_path", "")).strip()
    # 루트('/') 워크스페이스는 전체 디스크 탐색(find / 등) 같은 병리적 동작을 유발한다 —
    # 빈 값으로 대체해 기본 워크스페이스(settings.workspace)로 폴백시킨다.
    if workspace_path == "/":
        workspace_path = ""
    mode = str(body.get("mode", "")).strip()
    if mode not in ("chat", "work"):
        mode = ""
    # 작업 모드는 워크스페이스가 있어야 한다(홈·루트에서 작업하다 사고 방지).
    if mode == "work" and not workspace_path:
        return {"error": "작업 모드는 워크스페이스가 필요합니다."}
    room_id = await store.create_room(name, workspace_path, mode)
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
    if "mode" in body:
        mode = str(body.get("mode", "")).strip()
        # 작업 모드로 바꾸려면 워크스페이스가 있어야 한다.
        if mode == "work":
            room = await store.get_room(session_id)
            ws = room and room.get("workspace_path")
            if not ws or ws == os.path.expanduser("~") or ws == "/":
                return {"ok": False, "error": "작업 모드는 워크스페이스가 필요합니다."}
        await store.update_room_mode(session_id, mode if mode in ("chat", "work") else "")
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


@router.get("/sessions/{session_id}/tool-usage")
async def tool_usage(session_id: str):
    """세션에서 어떤 도구를 몇 번 호출했는지(eventlog 집계). read_file×9 처럼 툴별 카운트."""
    from .. import eventlog
    import collections
    counter: collections.Counter = collections.Counter()
    for r in eventlog.tail(session_id, limit=5000):
        if r.get("type") == "tool_call":
            counter[(r.get("data") or {}).get("name", "?")] += 1
    return {"tools": [{"name": n, "count": c} for n, c in counter.most_common()]}


@router.get("/sessions/{session_id}/context")
async def session_context(session_id: str):
    """마지막 LLM 호출의 context 영역별 분해(debug view) — 무엇이 컨텍스트를 차지하는지.
    system_base_role / memory / skills / history / tool_results 추정 토큰 + 총량·예산 대비 %."""
    return runtime.get_context_breakdown(session_id)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, since: int = 0):
    """seq > since 인 이벤트만 반환 — 폴링으로 SSE를 보완(프록시 버퍼링 내성).

    SSE와 eventlog는 같은 seq를 쓰므로, 폴링 응답을 seq로 dedup하면 중복 없이
    진행 상황을 이어 그릴 수 있다."""
    from .. import eventlog
    events = eventlog.tail(session_id, limit=1000, since=since)
    return {"events": [
        {"seq": e["seq"], "type": e["type"], "data": e["data"]} for e in events
    ]}


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
    await store.set_session_auto_approve(session_id, enabled)  # 영속화(resume가 복원)
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


@router.get("/rooms/{session_id}/git/remote")
async def git_remote(session_id: str, fetch: int = 1):
    """원격 대비 ahead/behind(=push/pull 필요 커밋 수). GitHub Desktop과 동일 지표.
    fetch=1이면 먼저 git fetch(네트워크)로 원격을 갱신한다."""
    ws = await _room_workspace(session_id)
    branch = _git(ws, "branch", "--show-current")
    if fetch:
        _git(ws, "fetch", "--quiet", timeout=40)  # 네트워크 — 타임아웃 넉넉히
    upstream = _git(ws, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream or "fatal" in upstream.lower() or "오류" in upstream or "no upstream" in upstream.lower():
        return {"branch": branch, "has_upstream": False, "ahead": 0, "behind": 0, "upstream": ""}
    # left-right --count: "behind<TAB>ahead" (left=upstream만, right=HEAD만)
    counts = _git(ws, "rev-list", "--left-right", "--count", f"{upstream}...HEAD").split()
    behind = int(counts[0]) if len(counts) == 2 and counts[0].isdigit() else 0
    ahead = int(counts[1]) if len(counts) == 2 and counts[1].isdigit() else 0
    return {"branch": branch, "has_upstream": True, "ahead": ahead, "behind": behind, "upstream": upstream}


@router.post("/rooms/{session_id}/git/push")
async def git_push(session_id: str):
    ws = await _room_workspace(session_id)
    return {"output": _git(ws, "push", timeout=90)}


@router.post("/rooms/{session_id}/git/pull")
async def git_pull(session_id: str):
    ws = await _room_workspace(session_id)
    return {"output": _git(ws, "pull", "--ff-only", timeout=90)}  # ff-only — 예기치 않은 머지 방지


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


# 잔액 조회는 DeepSeek API rate를 아끼려고 짧게 캐시한다(실패 시 캐시하지 않음).
_balance_cache: dict = {"ts": 0.0, "data": None}
BALANCE_CACHE_TTL = 60.0


@router.get("/admin/balance")
async def admin_balance():
    """DeepSeek 계정 잔액 — CNY 원본 + USD 환산값 + 충전 화면 URL."""
    global _balance_cache
    if _balance_cache["data"] and time.monotonic() - _balance_cache["ts"] < BALANCE_CACHE_TTL:
        return _balance_cache["data"]
    try:
        adapter = create_adapter(settings.deep_seek_model)
        raw = await adapter.fetch_balance()
        infos = raw.get("balance_infos") or []
        total = sum(float(i.get("total_balance") or 0) for i in infos)
        currency = infos[0].get("currency", "") if infos else ""
        # 잔액 API는 계정 통화로 반환한다(이 계정은 USD). CNY면 설정 환율로 근사 환산.
        if currency == "CNY":
            usd = round(total / settings.usd_cny_rate, 2) if total else 0.0
        else:
            usd = round(total, 2)
        data = {
            "ok": True,
            "currency": currency,
            "total": total,
            "usd": usd,
            "infos": infos,
            "top_up_url": settings.top_up_url,
        }
        _balance_cache = {"ts": time.monotonic(), "data": data}
        return data
    except Exception as err:
        error_log.record("balance_fetch_failed", str(err), "")
        return {"ok": False, "error": str(err)}


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


@router.get("/rooms/{session_id}/refinements")
async def room_refinements(session_id: str):
    """이 방의 개선 후보 — 대기 중 + 최근 결정분(rollback 가능하게 함께 반환)."""
    return {"refinements": await store.list_refinements(session_id)}


def _apply_refinement_file(row: dict, revert: bool) -> str:
    """승인된 refinement를 실제 skill 파일에 적용(또는 rollback 시 복원)한다.
    대상은 Project/Learned skill(.md)뿐 — Base Prompt는 건드리지 않는다(prompt drift 방지).
    before_text를 보존하므로 rollback이 항상 원상복구한다."""
    room = None
    scope = row.get("scope") or "project"
    target = row.get("target") or ""
    if not target or row.get("type") != "skill":
        return "skip"
    ws = (row.get("_ws") or "")
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", target).strip("-").lower()
    try:
        path = skills_lib.resolve_path(scope, ws, target, safe)
    except PermissionError:
        return "denied"
    if revert:
        before = row.get("before_text") or ""
        if before.strip():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(before, encoding="utf-8")
        elif path.is_file():
            path.unlink()  # 원래 없던 skill이면 삭제
        return "reverted"
    after = row.get("after_text") or row.get("proposed_change") or ""
    if not after.strip():
        return "empty"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(after, encoding="utf-8")
    return "applied"


@router.post("/refinements/{refinement_id}/decide")
async def decide_refinement(refinement_id: int, body: dict):
    """승인/무시/되돌리기.
    승인 = skill 파일에 실제 적용(Project/Learned만), 되돌리기 = before_text로 원상복구.
    무시 = 기록만. Base Prompt는 절대 건드리지 않는다."""
    decision = str(body.get("decision", ""))
    row = await store.decide_refinement(refinement_id, decision)
    if not row:
        return {"ok": False}
    applied = None
    if decision in ("approve", "rollback"):
        ws = await _room_workspace(row.get("session_id", ""))
        row["_ws"] = ws
        try:
            applied = _apply_refinement_file(row, revert=(decision == "rollback"))
        except Exception as err:
            applied = f"error: {err}"
        row.pop("_ws", None)
    return {"ok": True, "refinement": row, "applied": applied}


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
