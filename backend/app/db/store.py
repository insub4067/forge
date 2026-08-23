import json
import os
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update

from .models import (AgentRun, Checkpoint, Message, PushDevice, Refinement, ScheduledJob,
                     Session, Task, VisionAnalysis)
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


async def create_room(name: str, workspace_path: str = "", mode: str = "") -> str:
    room_id = uuid.uuid4().hex
    locked = bool(workspace_path)
    if not workspace_path:
        workspace_path = os.path.expanduser("~")
    async with async_session() as s:
        s.add(
            Session(
                id=room_id,
                title=name,
                workspace_path=workspace_path,
                workspace_locked=locked,
                mode=mode if mode in ("chat", "work") else "",
            )
        )
        await s.commit()
    return room_id


async def update_room_workspace(session_id: str, workspace_path: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.workspace_path = workspace_path
            await s.commit()


async def update_room_mode(session_id: str, mode: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess and mode in ("chat", "work", ""):
            sess.mode = mode
            await s.commit()


async def update_room_title(session_id: str, title: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.title = title
            await s.commit()


async def session_state(session_id: str) -> dict:
    """세션의 실행 상태(running/final_status). task facade·MCP 결과 조회용."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess is None:
            return {"exists": False, "running": False, "final_status": ""}
        return {"exists": True, "running": bool(sess.running), "final_status": sess.final_status or ""}


async def get_room(session_id: str) -> dict | None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess is None:
            return None
        return {
            "id": sess.id,
            "title": sess.title,
            "workspace_path": sess.workspace_path,
            "workspace_locked": sess.workspace_locked,
            "mode": sess.mode,
            "used_tokens": sess.used_tokens,
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


async def list_rooms() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Session, func.count(Message.id))
            .outerjoin(Message, Message.session_id == Session.id)
            .group_by(Session.id)
            .order_by(Session.created_at.desc())
        )
        # 예약 작업이 붙은 세션은 뱃지용으로 표시
        job_sids = {
            sid for (sid,) in (
                await s.execute(select(ScheduledJob.session_id).where(ScheduledJob.session_id != ""))
            ).all()
        }
        return [
            {
                "id": sess.id,
                "title": sess.title,
                "workspace_path": sess.workspace_path,
                "workspace_locked": sess.workspace_locked,
                "mode": sess.mode,
                "count": count,
                "used_tokens": sess.used_tokens,
                "logical_budget": sess.logical_budget,
                "running": sess.running,
                "scheduled": sess.id in job_sids,
            }
            for sess, count in result.all()
        ]


async def update_context_usage(session_id: str, used_tokens: int) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.used_tokens = used_tokens
            await s.commit()


async def mark_running(session_id: str, running: bool) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.running = running
            await s.commit()


async def set_session_auto_approve(session_id: str, enabled: bool) -> None:
    """세션의 승인 정책을 영속화한다 — durable resume가 이 값을 복원해 권한 확대를 막는다."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.auto_approve = bool(enabled)
            await s.commit()


async def get_session_auto_approve(session_id: str) -> bool:
    """세션의 승인 정책을 읽는다. 모르면 False(안전 — 자동 승인하지 않음)."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        return bool(sess.auto_approve) if sess else False


async def set_session_model_tier(session_id: str, tier: str) -> None:
    """세션의 모델 티어를 영속화한다 — durable resume가 이 값을 복원해
    재시작 후에도 같은 모델 정책으로 이어간다."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.model_tier = tier if tier in ("auto", "pro", "flash") else "auto"
            await s.commit()


async def get_session_model_tier(session_id: str) -> str:
    """세션의 모델 티어를 읽는다. 모르면 "auto"(기본 정책)."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        return sess.model_tier if sess and sess.model_tier else "auto"


async def reconcile_interrupted_runs() -> int:
    """서버 시작 시, running=True로 남은 세션은 재시작으로 중단된 run이다.
    복구 안내 메시지를 히스토리에 남기고 플래그를 내린다. 정리한 세션 수를 반환."""
    async with async_session() as s:
        result = await s.execute(select(Session).where(Session.running == True))  # noqa: E712
        stuck = result.scalars().all()
        ids = [sess.id for sess in stuck]
        for sess in stuck:
            sess.running = False
        await s.commit()
    note = {
        "role": "assistant",
        "content": "서버가 재시작되어 진행 중이던 작업이 중단되었습니다. 필요하면 다시 요청해주세요.",
    }
    for sid in ids:
        history = await load_history(sid)
        if history and history[-1].get("role") == "user":
            history.append(note)
            await save_history(sid, history)
    return len(ids)


async def take_interrupted_runs() -> list[dict]:
    """재시작으로 중단된(running=True) 세션을 찾아 running=False로 내리고 목록을 반환한다.
    재개할지(auto-resume) 안내 메시지만 남길지는 호출측이 final_status로 판단한다.
    각 항목: {id, final_status, workspace_path}."""
    async with async_session() as s:
        result = await s.execute(select(Session).where(Session.running == True))  # noqa: E712
        stuck = result.scalars().all()
        out = [{"id": x.id, "final_status": x.final_status or "",
                "workspace_path": x.workspace_path} for x in stuck]
        for x in stuck:
            x.running = False
        await s.commit()
    return out


async def mark_interrupted_note(session_id: str) -> None:
    """재개하지 않는 중단 세션에 안내 메시지를 남긴다(마지막이 user 턴일 때만)."""
    history = await load_history(session_id)
    if history and history[-1].get("role") == "user":
        history.append({"role": "assistant",
                        "content": "서버가 재시작되어 진행 중이던 작업이 중단되었습니다. 필요하면 다시 요청해주세요."})
        await save_history(session_id, history)


async def save_checkpoint(session_id: str, step_no: int, git_sha: str) -> None:
    async with async_session() as s:
        s.add(Checkpoint(session_id=session_id, step_no=step_no, git_sha=git_sha))
        await s.commit()


def task_key(title: str) -> str:
    """태스크 동일성 키. 모델이 같은 태스크의 제목에 괄호 주석을 덧붙이거나
    구두점을 바꿔도 같은 태스크로 본다("A" ↔ "A (이미 구현·테스트 완료)")."""
    t = re.sub(r"[(\[（【].*?[)\]）】]", " ", title or "")
    t = re.sub(r"[\s·,.:;\-—~/]+", " ", t).strip().lower()
    return t


def _match_task(existing: list[dict], key: str, used: set) -> dict | None:
    """같은 키 우선, 없으면 접두 일치(6자 이상 — 짧은 제목의 오매칭 방지)."""
    if not key:
        return None
    for e in existing:
        if e.get("id") in used:
            continue
        ek = task_key(e.get("title", ""))
        if ek == key:
            return e
    for e in existing:
        if e.get("id") in used:
            continue
        ek = task_key(e.get("title", ""))
        if len(key) >= 6 and len(ek) >= 6 and (ek.startswith(key) or key.startswith(ek)):
            return e
    return None


def merge_tasks(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """태스크 신원을 유지한 병합(순수 함수 — DB 없이 검증 가능).

    모델은 매번 전체 목록을 다시 보내고 제목도 조금씩 고쳐 쓴다. 제목을 신원으로
    삼으면 같은 태스크가 새 태스크로 다시 생겨 목록이 중복된다. 그래서 키로 기존
    태스크를 찾아 **id와 최초 제목을 유지**하고 상태/진행률만 갱신한다.
    한 요청 안에 같은 키가 두 번 오면 첫 번째만 남긴다.
    반환 항목의 id가 None이면 새로 만들 태스크, 아니면 기존 태스크 갱신.
    """
    out: list[dict] = []
    used: set = set()
    seen: set = set()
    for t in incoming:
        title = str(t.get("title", "")).strip()
        if not title:
            continue
        key = task_key(title)
        if key in seen:
            continue
        seen.add(key)
        m = _match_task(existing, key, used)
        prog = t.get("progress")
        if m:
            used.add(m.get("id"))
            out.append({
                "id": m.get("id"),
                "title": m.get("title", title),   # 제목은 처음 것을 유지(표시 흔들림 방지)
                "status": str(t.get("status", m.get("status", "todo"))),
                "progress": int(prog if prog is not None else m.get("progress", 0) or 0),
            })
        else:
            out.append({
                "id": None,
                "title": title,
                "status": str(t.get("status", "todo")),
                "progress": int(prog or 0),
            })
    return out


async def replace_tasks(session_id: str, tasks: list[dict]) -> list[dict]:
    """모델이 준 목록으로 태스크를 갱신하고, 신원이 유지된 최종 목록을 반환한다."""
    async with async_session() as s:
        rows = (await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )).scalars().all()
        by_id = {r.id: r for r in rows}
        existing = [{"id": r.id, "title": r.title, "status": r.status,
                     "progress": r.progress} for r in rows]
        merged = merge_tasks(existing, tasks)
        keep: set = set()
        for m in merged:
            row = by_id.get(m["id"]) if m["id"] is not None else None
            if row is None:
                row = Task(session_id=session_id, title=m["title"],
                           status=m["status"], progress=m["progress"])
                s.add(row)
            else:
                row.status = m["status"]
                row.progress = m["progress"]
                keep.add(row.id)
        for r in rows:
            if r.id not in keep:
                await s.delete(r)
        await s.commit()
        result = (await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )).scalars().all()
        return [{"id": r.id, "title": r.title, "status": r.status,
                 "progress": r.progress} for r in result]


async def list_tasks(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(Task).where(Task.session_id == session_id).order_by(Task.id)
        )
        return [
            {"id": t.id, "title": t.title, "status": t.status, "progress": t.progress}
            for t in result.scalars()
        ]


async def save_agent_run(
    session_id: str,
    role: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    thinking_enabled: bool = False,
    reasoning_effort: str = "",
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    model_calls: int = 0,
    tool_calls: int = 0,
    retries: int = 0,
    compactions: int = 0,
    elapsed_ms: int = 0,
    selected_skill_count: int = 0,
    selected_skills: str = "",
    tool_raw_tokens: int = 0,
    tool_visible_tokens: int = 0,
) -> None:
    async with async_session() as s:
        s.add(
            AgentRun(
                session_id=session_id,
                role=role,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                thinking_enabled=thinking_enabled,
                reasoning_effort=reasoning_effort,
                cache_hit_tokens=cache_hit_tokens,
                cache_miss_tokens=cache_miss_tokens,
                model_calls=model_calls,
                tool_calls=tool_calls,
                retries=retries,
                compactions=compactions,
                elapsed_ms=elapsed_ms,
                selected_skill_count=selected_skill_count,
                selected_skills=selected_skills,
                tool_raw_tokens=tool_raw_tokens,
                tool_visible_tokens=tool_visible_tokens,
            )
        )
        await s.commit()


async def set_session_final_status(session_id: str, final_status: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.final_status = final_status
            await s.commit()


async def save_vision_analysis(
    session_id: str,
    task_id: str,
    analysis_result: str,
    image_path: str = "",
    issues: str = "",
) -> None:
    async with async_session() as s:
        s.add(
            VisionAnalysis(
                session_id=session_id,
                task_id=task_id,
                image_path=image_path,
                analysis_result=analysis_result,
                issues=issues,
            )
        )
        await s.commit()


async def session_agent_runs(session_id: str) -> list[dict]:
    async with async_session() as s:
        result = await s.execute(
            select(AgentRun)
            .where(AgentRun.session_id == session_id)
            .order_by(AgentRun.created_at.desc())
        )
        return [
            {
                "role": r.role,
                "model": r.model,
                "thinking_enabled": r.thinking_enabled,
                "reasoning_effort": r.reasoning_effort,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "cache_hit_tokens": r.cache_hit_tokens,
                "cache_miss_tokens": r.cache_miss_tokens,
                "model_calls": r.model_calls,
                "tool_calls": r.tool_calls,
                "retries": r.retries,
                "compactions": r.compactions,
                "elapsed_ms": r.elapsed_ms,
                "selected_skill_count": r.selected_skill_count,
                "selected_skills": r.selected_skills,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in result.scalars()
        ]


def _aggregate_runs(runs: list) -> dict:
    """AgentRun ORM 행 목록을 집계한다(세션/전체 공용)."""
    prompt = sum(r.prompt_tokens for r in runs)
    completion = sum(r.completion_tokens for r in runs)
    hit = sum(r.cache_hit_tokens for r in runs)
    miss = sum(r.cache_miss_tokens for r in runs)
    role_tokens: dict[str, int] = {}
    role_calls: dict[str, int] = {}
    model_tokens: dict[str, int] = {}
    model_calls: dict[str, int] = {}
    for r in runs:
        role_tokens[r.role] = role_tokens.get(r.role, 0) + r.prompt_tokens + r.completion_tokens
        role_calls[r.role] = role_calls.get(r.role, 0) + 1
        m = r.model or "unknown"
        model_tokens[m] = model_tokens.get(m, 0) + r.prompt_tokens + r.completion_tokens
        model_calls[m] = model_calls.get(m, 0) + 1
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "cache_hit_ratio": round(hit / (hit + miss), 3) if (hit + miss) else 0,
        "total_model_calls": sum(r.model_calls for r in runs),
        "total_tool_calls": sum(r.tool_calls for r in runs),
        "total_retries": sum(r.retries for r in runs),
        "total_compactions": sum(r.compactions for r in runs),
        "elapsed_ms": sum(r.elapsed_ms for r in runs),
        "pro_calls": sum(1 for r in runs if "pro" in (r.model or "").lower()),
        # RTK식 gain — 도구 결과 압축 전/후·절감률(도구 출력 한정 지표. 전체 API 토큰과 구분).
        "tool_raw_tokens": sum(getattr(r, "tool_raw_tokens", 0) or 0 for r in runs),
        "tool_visible_tokens": sum(getattr(r, "tool_visible_tokens", 0) or 0 for r in runs),
        "role_tokens": role_tokens,
        "role_calls": role_calls,
        "model_tokens": model_tokens,
        "model_calls": model_calls,
    }


async def session_metrics(session_id: str) -> dict:
    """세션 하나의 비용 집계(가격 계산은 API 계층에서 metrics.py로 덧붙임)."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        result = await s.execute(select(AgentRun).where(AgentRun.session_id == session_id))
        runs = result.scalars().all()
    agg = _aggregate_runs(runs)
    agg["final_status"] = (sess.final_status if sess else "") or ("running" if sess and sess.running else "")
    agg["developer_calls"] = agg["role_calls"].get("developer", 0)
    skills = [r.selected_skills for r in runs if r.selected_skills]
    agg["selected_skills"] = skills[0] if skills else ""
    return agg


async def register_device(name: str, endpoint: str, subscription_json: str) -> None:
    """푸시 기기 등록/갱신(endpoint로 중복 방지)."""
    async with async_session() as s:
        result = await s.execute(select(PushDevice).where(PushDevice.endpoint == endpoint))
        dev = result.scalar_one_or_none()
        if dev:
            dev.subscription_json = subscription_json
            if name:
                dev.name = name
        else:
            s.add(PushDevice(name=name, endpoint=endpoint, subscription_json=subscription_json))
        await s.commit()


async def list_devices() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(select(PushDevice).order_by(PushDevice.created_at.desc()))
        return [
            {
                "id": d.id,
                "name": d.name,
                "created_at": d.created_at.isoformat() if d.created_at else "",
                "last_seen": d.last_seen.isoformat() if d.last_seen else "",
            }
            for d in result.scalars()
        ]


async def delete_device(device_id: int) -> None:
    async with async_session() as s:
        await s.execute(delete(PushDevice).where(PushDevice.id == device_id))
        await s.commit()


async def all_subscriptions() -> list[dict]:
    """모든 기기의 push 구독 정보(발송용)."""
    import json as _json
    async with async_session() as s:
        result = await s.execute(select(PushDevice))
        out = []
        for d in result.scalars():
            try:
                out.append(_json.loads(d.subscription_json))
            except Exception:
                continue
        return out


async def all_runs_for_cost() -> list[dict]:
    """전체 agent_run의 비용 계산용 최소 필드."""
    async with async_session() as s:
        runs = (await s.execute(select(AgentRun))).scalars().all()
    return [
        {
            "model": r.model,
            "cache_hit_tokens": r.cache_hit_tokens,
            "cache_miss_tokens": r.cache_miss_tokens,
            "completion_tokens": r.completion_tokens,
        }
        for r in runs
    ]


async def metrics_summary() -> dict:
    """전체 세션의 성공률·토큰·비용 집계. cost per successfully completed task 판단용."""
    async with async_session() as s:
        srows = (await s.execute(select(Session))).scalars().all()
        aruns = (await s.execute(select(AgentRun))).scalars().all()

    # 삭제된 세션의 orphan run은 세션 단위 지표에서 제외(비율이 1을 넘는 것 방지).
    valid = {x.id for x in srows}
    aruns = [r for r in aruns if r.session_id in valid]

    by_session: dict[str, list] = {}
    for r in aruns:
        by_session.setdefault(r.session_id, []).append(r)

    total = len(srows)
    successful = sum(1 for x in srows if x.final_status == "completed")
    agg = _aggregate_runs(aruns)

    # 세션 단위 파생 지표 — 권위 있는 세션 목록(srows)을 기준으로 순회
    pro_sessions = 0
    first_pass = 0  # Sr(pro) 승격 없이 완료 = Developer가 한 번에 성공
    success_tokens = 0
    success_model_calls = 0
    success_elapsed = 0
    for sess in srows:
        runs = by_session.get(sess.id, [])
        has_pro = any("pro" in (r.model or "").lower() for r in runs)
        if has_pro:
            pro_sessions += 1
        if sess.final_status == "completed":
            success_tokens += sum(r.prompt_tokens + r.completion_tokens for r in runs)
            success_model_calls += sum(r.model_calls for r in runs)
            success_elapsed += sum(r.elapsed_ms for r in runs)
            if not has_pro:
                first_pass += 1

    status_counts: dict[str, int] = {}
    for x in srows:
        key = x.final_status or "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1

    agg.update({
        "sessions": total,
        "successful": successful,
        "success_rate": round(successful / total, 3) if total else 0,
        "avg_tokens_per_success": round(success_tokens / successful) if successful else 0,
        "avg_model_calls_per_success": round(success_model_calls / successful, 2) if successful else 0,
        "avg_elapsed_ms_per_success": round(success_elapsed / successful) if successful else 0,
        "pro_escalation_rate": round(pro_sessions / total, 3) if total else 0,
        "review_first_pass_rate": round(first_pass / successful, 3) if successful else 0,
        "status_counts": status_counts,
    })
    return agg


async def admin_stats(days: int = 7) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    async with async_session() as s:
        result = await s.execute(select(AgentRun).where(AgentRun.created_at >= since))
        runs = result.scalars().all()

        total_prompt = sum(r.prompt_tokens for r in runs)
        total_completion = sum(r.completion_tokens for r in runs)

        role_counts: dict[str, int] = {}
        role_tokens: dict[str, int] = {}
        model_counts: dict[str, int] = {}
        model_tokens: dict[str, int] = {}
        for r in runs:
            role_counts[r.role] = role_counts.get(r.role, 0) + 1
            role_tokens[r.role] = role_tokens.get(r.role, 0) + r.prompt_tokens + r.completion_tokens
            m = r.model or "unknown"
            model_counts[m] = model_counts.get(m, 0) + 1
            model_tokens[m] = model_tokens.get(m, 0) + r.prompt_tokens + r.completion_tokens

        total_runs = len(runs)
        # 현재 아키텍처의 활성 역할만 노출한다(과거 planner/coder/reviewer/debugger 제외).
        active_roles = {"triage", "developer", "chat", "vision"}
        roles = [
            {
                "role": role,
                "count": count,
                "percent": round(count / total_runs * 100, 1) if total_runs else 0,
                "tokens": role_tokens.get(role, 0),
            }
            for role, count in sorted(role_counts.items(), key=lambda x: -x[1])
            if role in active_roles
        ]

        room_counts: dict[str, int] = {}
        for r in runs:
            room_counts[r.session_id] = room_counts.get(r.session_id, 0) + 1
        rooms = [
            {"session_id": sid, "count": c}
            for sid, c in sorted(room_counts.items(), key=lambda x: -x[1])
        ]

        # 모델별 집계 — flash/pro 등 LLM 모델 단위 토큰 소비 비교용.
        models = [
            {
                "model": m,
                "count": model_counts[m],
                "tokens": model_tokens[m],
                "percent": round(model_tokens[m] / (total_prompt + total_completion) * 100, 1)
                if (total_prompt + total_completion) else 0,
            }
            for m in sorted(model_tokens, key=lambda x: -model_tokens[x])
        ]

        return {
            "days": days,
            "total_runs": total_runs,
            "total_tokens": total_prompt + total_completion,
            "total_prompt": total_prompt,
            "total_completion": total_completion,
            "roles": roles,
            "models": models,
            "rooms": rooms,
        }


def _job_dict(j) -> dict:
    return {
        "id": j.id, "name": j.name, "prompt": j.prompt,
        "workspace_path": j.workspace_path, "session_id": j.session_id,
        "timezone": j.timezone,
        "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
        "recurrence": j.recurrence, "recurrence_value": j.recurrence_value,
        "auto_approve": j.auto_approve, "enabled": j.enabled, "status": j.status,
        "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
        "last_result": j.last_result,
        "retries": j.retries, "max_retries": j.max_retries,
    }


async def create_job(data: dict) -> dict:
    async with async_session() as s:
        j = ScheduledJob(
            name=data.get("name", ""), prompt=data.get("prompt", ""),
            workspace_path=data.get("workspace_path", ""),
            session_id=data.get("session_id", ""),
            timezone=data.get("timezone", "Asia/Seoul"),
            next_run_at=data.get("next_run_at"),
            recurrence=data.get("recurrence", ""),
            recurrence_value=data.get("recurrence_value", ""),
            auto_approve=bool(data.get("auto_approve", True)),
            max_retries=int(data.get("max_retries", 0) or 0),
        )
        s.add(j)
        await s.commit()
        await s.refresh(j)
        return _job_dict(j)


async def list_jobs() -> list[dict]:
    async with async_session() as s:
        result = await s.execute(select(ScheduledJob).order_by(ScheduledJob.created_at.desc()))
        return [_job_dict(j) for j in result.scalars()]


async def get_job(job_id: int) -> dict | None:
    async with async_session() as s:
        j = await s.get(ScheduledJob, job_id)
        return _job_dict(j) if j else None


async def update_job(job_id: int, fields: dict) -> None:
    async with async_session() as s:
        j = await s.get(ScheduledJob, job_id)
        if not j:
            return
        for k, v in fields.items():
            if hasattr(j, k):
                setattr(j, k, v)
        await s.commit()


async def delete_job(job_id: int) -> None:
    async with async_session() as s:
        await s.execute(delete(ScheduledJob).where(ScheduledJob.id == job_id))
        await s.commit()


async def due_jobs(now_utc) -> list[dict]:
    """실행 시각이 지난 enabled 잡. next_run_at이 authoritative."""
    async with async_session() as s:
        result = await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.enabled == True,  # noqa: E712
                ScheduledJob.next_run_at.is_not(None),
                ScheduledJob.next_run_at <= now_utc,
                ScheduledJob.status != "running",
            )
        )
        return [_job_dict(j) for j in result.scalars()]


async def claim_job(job_id: int) -> bool:
    """잡을 원자적으로 선점한다. 이미 running이면 False — 중복 실행 방지."""
    async with async_session() as s:
        result = await s.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.id == job_id,
                ScheduledJob.status != "running",
            )
            .values(status="running")
        )
        await s.commit()
        return result.rowcount > 0


# ── Refinement(개선 후보) — 근거 축적·승인·rollback. 승인해도 자동 적용은 하지 않는다. ──

_DECISIONS = {"approve": "approved", "ignore": "ignored", "rollback": "pending"}


def _refinement_dict(r: Refinement) -> dict:
    return {
        "id": r.id,
        "session_id": r.session_id,
        "type": r.type,
        "scope": r.scope,
        "target": r.target,
        "proposed_change": r.proposed_change,
        "before_text": r.before_text,
        "after_text": r.after_text,
        "evidence_runs": json.loads(r.evidence_runs or "[]"),
        "evidence": json.loads(r.evidence_json or "{}"),
        "failure_pattern": r.failure_pattern,
        "expected_effect": r.expected_effect,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "decided_at": r.decided_at.isoformat() if r.decided_at else "",
    }


async def save_refinement(session_id: str, candidate: dict) -> dict | None:
    """후보 1건 저장. 같은 failure_pattern이 이미 있으면 저장하지 않는다(None).

    같은 실패가 반복될 때마다 같은 후보를 다시 띄우면 알림 소음이 된다.
    사용자가 무시한 후보를 되살리지도 않는다(무시는 결정이다).
    """
    pattern = candidate.get("failure_pattern", "")
    async with async_session() as s:
        if pattern:
            dup = (await s.execute(
                select(Refinement).where(Refinement.failure_pattern == pattern)
            )).scalars().first()
            if dup:
                return None
        row = Refinement(
            session_id=session_id,
            type=candidate.get("type", "skill"),
            scope=candidate.get("scope", "project"),
            target=candidate.get("target", ""),
            proposed_change=candidate.get("proposed_change", ""),
            before_text=candidate.get("before_text", ""),
            after_text=candidate.get("after_text", ""),
            evidence_runs=json.dumps(candidate.get("evidence_runs", []), ensure_ascii=False),
            evidence_json=json.dumps(candidate.get("evidence", {}), ensure_ascii=False),
            failure_pattern=pattern,
            expected_effect=candidate.get("expected_effect", ""),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return _refinement_dict(row)


async def list_refinements(session_id: str = "", limit: int = 10) -> list[dict]:
    """최근 후보(대기 중 + 최근 결정분). 결정된 것도 보여야 rollback을 누를 수 있다."""
    q = select(Refinement).order_by(Refinement.id.desc()).limit(limit)
    if session_id:
        q = select(Refinement).where(Refinement.session_id == session_id) \
            .order_by(Refinement.id.desc()).limit(limit)
    async with async_session() as s:
        rows = (await s.execute(q)).scalars().all()
    return [_refinement_dict(r) for r in rows]


async def decide_refinement(refinement_id: int, decision: str) -> dict | None:
    """승인/무시/되돌리기. 승인은 '기록'일 뿐 파일을 바꾸지 않는다(적용은 다음 단계)."""
    status = _DECISIONS.get(decision)
    if not status:
        return None
    async with async_session() as s:
        row = await s.get(Refinement, refinement_id)
        if not row:
            return None
        row.status = status
        row.decided_at = None if status == "pending" else datetime.utcnow()
        await s.commit()
        await s.refresh(row)
        return _refinement_dict(row)
