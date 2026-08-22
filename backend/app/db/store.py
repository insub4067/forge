import json
import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from .models import AgentRun, Checkpoint, Message, Session, Task, VisionAnalysis
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


async def create_room(name: str, workspace_path: str = "") -> str:
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


async def update_room_title(session_id: str, title: str) -> None:
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        if sess:
            sess.title = title
            await s.commit()


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
        return [
            {
                "id": sess.id,
                "title": sess.title,
                "workspace_path": sess.workspace_path,
                "workspace_locked": sess.workspace_locked,
                "count": count,
                "used_tokens": sess.used_tokens,
                "logical_budget": sess.logical_budget,
                "running": sess.running,
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


async def save_checkpoint(session_id: str, step_no: int, git_sha: str) -> None:
    async with async_session() as s:
        s.add(Checkpoint(session_id=session_id, step_no=step_no, git_sha=git_sha))
        await s.commit()


async def replace_tasks(session_id: str, tasks: list[dict]) -> None:
    async with async_session() as s:
        await s.execute(delete(Task).where(Task.session_id == session_id))
        for t in tasks:
            s.add(
                Task(
                    session_id=session_id,
                    title=str(t.get("title", "")),
                    status=str(t.get("status", "todo")),
                    progress=int(t.get("progress", 0)),
                )
            )
        await s.commit()


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
    for r in runs:
        role_tokens[r.role] = role_tokens.get(r.role, 0) + r.prompt_tokens + r.completion_tokens
        role_calls[r.role] = role_calls.get(r.role, 0) + 1
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
        "role_tokens": role_tokens,
        "role_calls": role_calls,
    }


async def session_metrics(session_id: str) -> dict:
    """세션 하나의 비용 집계(가격 계산은 API 계층에서 metrics.py로 덧붙임)."""
    async with async_session() as s:
        sess = await s.get(Session, session_id)
        result = await s.execute(select(AgentRun).where(AgentRun.session_id == session_id))
        runs = result.scalars().all()
    agg = _aggregate_runs(runs)
    agg["final_status"] = (sess.final_status if sess else "") or ("running" if sess and sess.running else "")
    agg["planner_calls"] = agg["role_calls"].get("planner", 0)
    agg["reviewer_calls"] = agg["role_calls"].get("reviewer", 0)
    agg["debugger_calls"] = agg["role_calls"].get("debugger", 0)
    skills = [r.selected_skills for r in runs if r.selected_skills]
    agg["selected_skills"] = skills[0] if skills else ""
    return agg


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
    debugger_sessions = 0
    review_first_pass = 0
    success_tokens = 0
    success_model_calls = 0
    success_elapsed = 0
    for sess in srows:
        runs = by_session.get(sess.id, [])
        has_pro = any("pro" in (r.model or "").lower() for r in runs)
        has_debugger = any(r.role == "debugger" for r in runs)
        if has_pro:
            pro_sessions += 1
        if has_debugger:
            debugger_sessions += 1
        if sess.final_status == "completed":
            success_tokens += sum(r.prompt_tokens + r.completion_tokens for r in runs)
            success_model_calls += sum(r.model_calls for r in runs)
            success_elapsed += sum(r.elapsed_ms for r in runs)
            # Coder→Reviewer→completed(Debugger 없이) = 첫 리뷰 통과
            if not has_debugger:
                review_first_pass += 1

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
        "debugger_activation_rate": round(debugger_sessions / total, 3) if total else 0,
        "review_first_pass_rate": round(review_first_pass / successful, 3) if successful else 0,
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
        for r in runs:
            role_counts[r.role] = role_counts.get(r.role, 0) + 1
            role_tokens[r.role] = role_tokens.get(r.role, 0) + r.prompt_tokens + r.completion_tokens

        total_runs = len(runs)
        roles = [
            {
                "role": role,
                "count": count,
                "percent": round(count / total_runs * 100, 1) if total_runs else 0,
                "tokens": role_tokens.get(role, 0),
            }
            for role, count in sorted(role_counts.items(), key=lambda x: -x[1])
        ]

        room_counts: dict[str, int] = {}
        for r in runs:
            room_counts[r.session_id] = room_counts.get(r.session_id, 0) + 1
        rooms = [
            {"session_id": sid, "count": c}
            for sid, c in sorted(room_counts.items(), key=lambda x: -x[1])
        ]

        return {
            "days": days,
            "total_runs": total_runs,
            "total_tokens": total_prompt + total_completion,
            "total_prompt": total_prompt,
            "total_completion": total_completion,
            "roles": roles,
            "rooms": rooms,
        }
