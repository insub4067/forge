"""올인원 오케스트레이션 결정적 검증 — Triage → Chat | Developer(+Sr 승격 재시도).

LLM/네트워크 없이 _run_role·store를 목킹해 run()의 흐름만 검증한다.
실행: python test_developer_loop.py
"""
import asyncio

from app.runtime import agent as A


def make_runtime(role_status="done", route_kind="code"):
    rt = A.AgentRuntime()
    calls = []  # (role, escalate)

    async def fake_run_role(role, all_messages, send, session_id, ws, state,
                            recent_calls, step_base, room_memory="", retry_count=0,
                            tools=None, skills="", complexity="normal", escalate=False, has_image=False):
        calls.append((role, escalate))
        st = role_status(role, len(calls), escalate) if callable(role_status) else role_status
        return st, 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}

    rt._run_role = fake_run_role

    async def fake_triage(all_messages):
        return route_kind, 0, 0
    rt._triage = fake_triage

    A.store.save_agent_run = lambda *a, **k: _noop()
    A.store.update_context_usage = lambda *a, **k: _noop()
    A.store.ensure_session = lambda *a, **k: _noop()
    A.store.save_history = lambda *a, **k: _noop()
    A.store.set_session_final_status = lambda *a, **k: _noop()
    return rt, calls


async def _noop():
    return None


async def run_case(rt, cancel_after_events=None):
    events = []

    async def emit(evt):
        events.append(evt)
        if cancel_after_events and len(events) == cancel_after_events:
            rt.cancel("s1")

    await rt.run([{"role": "user", "content": "작업"}], emit, "s1", None)
    done = [e for e in events if e["type"] == "done"]
    return (done[-1]["data"] if done else {}), events


def roles_of(calls):
    return [r for r, _ in calls]


async def main():
    # Case A — 정상: triage(agent) → developer 1회 → completed
    rt, calls = make_runtime("done")
    data, _ = await run_case(rt)
    assert roles_of(calls) == ["developer"], roles_of(calls)
    assert data.get("status") == "completed", data
    print("Case A (정상 1패스): OK", roles_of(calls))

    # Case B — 1차 막힘(max_steps) → Sr 승격 재시도(escalate) → done
    def stuck_then_ok(role, n, escalate):
        return "done" if escalate else "max_steps"
    rt, calls = make_runtime(stuck_then_ok)
    data, _ = await run_case(rt)
    assert roles_of(calls) == ["developer", "developer"], roles_of(calls)
    assert calls[0][1] is False and calls[1][1] is True, calls  # 2차만 escalate
    assert data.get("status") == "completed", data
    print("Case B (막힘→Sr 승격→성공): OK", calls)

    # Case C — 계속 막힘 → 최초 1회 + MAX_ESCALATIONS(2) 승격 = 총 3회 후 max_steps 종료
    rt, calls = make_runtime("max_steps")
    data, _ = await run_case(rt)
    assert roles_of(calls) == ["developer"] * (1 + A.MAX_ESCALATIONS), roles_of(calls)
    assert [e for _, e in calls] == [False, True, True], calls
    assert data.get("status") == "max_steps", data
    print("Case C (계속 막힘→승격 루프 상한→종료): OK", len(calls), "회")

    # Case D — 중단: developer가 cancelled 반환(승격 재시도 안 함)
    rt, calls = make_runtime("cancelled")
    data, _ = await run_case(rt)
    assert roles_of(calls) == ["developer"], roles_of(calls)
    assert data.get("status") == "cancelled", data
    print("Case D (중단): OK")

    # Case E — context limit: 승격 재시도 대상 아님(즉시 종료)
    rt, calls = make_runtime("context_blocked")
    data, _ = await run_case(rt)
    assert roles_of(calls) == ["developer"], roles_of(calls)
    assert data.get("status") == "context_blocked", data
    print("Case E (context limit): OK")

    # Case F — 단순 대화: triage=chat → chat 역할만(developer 호출 안 함, 최저가 flash)
    rt, calls = make_runtime("done", route_kind="chat")
    data, _ = await run_case(rt)
    assert roles_of(calls) == ["chat"], roles_of(calls)
    assert data.get("status") == "completed", data
    print("Case F (단순 대화→chat 최저가): OK", roles_of(calls))

    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
