"""실행 기록·비용(ledger) 및 AgentRun 메트릭 — store.py에서 분리한 도메인 모듈."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update

from .models import AgentRun, Session, ToolLedger
from .session import async_session


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


async def ledger_start(session_id: str, run_id: str, tool_name: str, args_hash: str) -> str:
    """실행 **직전** started를 기록하고 ledger id를 준다. 실패하면 빈 문자열(장부는 fail-open —
    장부 오류가 도구 실행을 막으면 정상 작업이 죽는다)."""
    lid = uuid.uuid4().hex
    async with async_session() as s:
        s.add(ToolLedger(id=lid, session_id=session_id, run_id=run_id or "",
                         tool_name=tool_name, args_hash=args_hash, status="started"))
        await s.commit()
    return lid


async def ledger_complete(ledger_id: str) -> None:
    """history 저장까지 끝난 뒤 started → completed로 닫는다. 저장 전에 닫으면 안 된다 —
    닫힌 행은 '재실행해도 안전한 기록된 실행'을 뜻하기 때문이다."""
    async with async_session() as s:
        await s.execute(update(ToolLedger).where(ToolLedger.id == ledger_id)
                        .values(status="completed", completed_at=datetime.utcnow()))
        await s.commit()
