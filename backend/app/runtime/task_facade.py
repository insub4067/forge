"""ForgeRuntime task facade — execute/status/result/cancel의 단일 진입점.

MCP proposal §17의 Runtime Boundary. REST(/api/chat)와 MCP 서버가 같은 facade를 호출해
task 단위(goal → task_id → status → result)로 agent를 위임한다. task_id = session_id다.
기존 AgentRuntime·store를 재사용하고 새 실행 경로를 만들지 않는다.
"""
import asyncio
import uuid

from ..db import store


async def execute(goal: str, workspace: str = "", auto_approve: bool = False, plan: str = "") -> str:
    """새 task를 시작하고 즉시 task_id를 반환한다(비차단). agent run은 백그라운드에서 돈다.

    plan이 주어지면(상위 MCP 호출부가 추론·계획을 담당) FORGE 내부 planner를 건너뛰고
    코딩만 한다 — 가장 비싼 planner phase를 외부(무제한 chat 모델)로 넘겨 비용을 줄인다.
    """
    from ..api.routes import runtime, _notify_done  # 지연 import(순환 방지)
    from .. import errors as error_log

    sid = uuid.uuid4().hex
    await store.ensure_session(sid, goal[:40] or "task", workspace or None)
    runtime.set_auto_approve(sid, auto_approve)
    runtime.try_begin(sid)  # 새 세션이라 항상 성공
    # 계획을 주면 Developer의 컨텍스트에 실어 그대로 따르게 한다(별도 planner 없음).
    if plan.strip():
        content = f"[상위 에이전트가 제공한 계획]\n{plan.strip()}\n\n[목표]\n{goal}"
    else:
        content = goal
    history = [{"role": "user", "content": content}]
    await store.save_history(sid, history)
    await store.mark_running(sid, True)

    async def _run():
        async def _emit(_evt):
            return None  # 관중 없음 — status/result가 DB에서 조회
        try:
            new_history = await runtime.run(history, _emit, sid, workspace or None)
            await store.save_history(sid, new_history)
            await _notify_done(sid, new_history)
        except Exception as err:
            error_log.record("task_facade", str(err), sid)
            history.append({"role": "assistant", "content": f"작업 중 오류로 중단: {str(err)[:300]}"})
            await store.save_history(sid, history)
        finally:
            await store.mark_running(sid, False)
            runtime.cleanup_session(sid)

    asyncio.create_task(_run())
    return sid


def status(task_id: str) -> dict:
    """task 라이브 상태(running/role/waiting_for/pending). 스트림 없이 조회 가능."""
    from ..api.routes import runtime
    st = dict(runtime.get_status(task_id))
    st["running"] = runtime.is_running(task_id)
    return st


async def result(task_id: str) -> dict:
    """완료된 task의 결과 — final_status, 요약(마지막 assistant 메시지), 비용·토큰."""
    from ..metrics import sum_cost
    state = await store.session_state(task_id)
    history = await store.load_history(task_id)
    summary = ""
    for m in reversed(history):
        if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip():
            summary = m["content"]
            break
    rows = await store.session_agent_runs(task_id)
    cost, priced, _ = sum_cost(rows)
    total_tok = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows)
    return {
        "task_id": task_id,
        "final_status": state["final_status"],
        "running": state["running"],
        "summary": summary,
        "cost": cost if priced else None,
        "total_tokens": total_tok,
    }


def cancel(task_id: str) -> bool:
    from ..api.routes import runtime
    if not runtime.is_running(task_id):
        return False
    runtime.cancel(task_id)
    return True
