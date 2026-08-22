"""자기수정 루프(Reviewer↔Debugger) 상태머신 결정적 검증.

LLM/네트워크 없이 _run_role·store를 목킹해 run()의 오케스트레이션만 검증한다.
실행: python test_review_loop.py
"""
import asyncio

from app.runtime import agent as A


def make_runtime(role_status="done"):
    rt = A.AgentRuntime()
    calls = []  # (role, retry_count)

    async def fake_run_role(role, all_messages, send, session_id, ws, state,
                            recent_calls, step_base, room_memory="", retry_count=0, tools=None):
        calls.append((role, retry_count))
        # 시나리오별로 role_status를 콜러블로 줄 수 있게
        st = role_status(role, len(calls)) if callable(role_status) else role_status
        return st, 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}

    rt._run_role = fake_run_role

    async def fake_triage(all_messages):
        return "agent", 0, 0
    rt._triage = fake_triage

    # store 목킹
    A.store.save_agent_run = lambda *a, **k: _noop()
    A.store.update_context_usage = lambda *a, **k: _noop()
    A.store.ensure_session = lambda *a, **k: _noop()
    A.store.save_history = lambda *a, **k: _noop()
    return rt, calls


async def _noop():
    return None


def set_tasks(seq):
    """list_tasks가 호출될 때마다 seq에서 하나씩 반환."""
    it = iter(seq)
    last = [seq[-1]]

    async def fake_list_tasks(session_id):
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]
    A.store.list_tasks = fake_list_tasks


async def run_case(rt, tasks_seq, cancel_after_events=None):
    events = []

    async def emit(evt):
        events.append(evt)
        if cancel_after_events and len(events) == cancel_after_events:
            rt.cancel("s1")

    set_tasks(tasks_seq)
    await rt.run([{"role": "user", "content": "작업"}], emit, "s1", None)
    done = [e for e in events if e["type"] == "done"]
    return done[-1]["data"] if done else {}, events


def roles_of(calls):
    return [r for r, _ in calls]


async def main():
    D = lambda: [{"title": "t", "status": "done"}]
    DEBUG = lambda: [{"title": "t", "status": "debug"}]

    # Case A — 정상 성공: reviewer 1회 → 전부 done
    rt, calls = make_runtime("done")
    data, _ = await run_case(rt, [D()])
    assert roles_of(calls) == ["planner", "coder", "reviewer"], roles_of(calls)
    assert data.get("status") == "completed", data
    print("Case A (정상 성공): OK", roles_of(calls))

    # Case B — Reviewer 실패 1회 → Debugger → Reviewer → done
    rt, calls = make_runtime("done")
    data, _ = await run_case(rt, [DEBUG(), D()])
    assert roles_of(calls) == ["planner", "coder", "reviewer", "debugger", "reviewer"], roles_of(calls)
    assert data.get("status") == "completed", data
    print("Case B (실패→수정→성공): OK", roles_of(calls))

    # Case C — 반복 실패: 계속 debug → review_limit, 마지막 debugger가 Pro 승격(retry>=3)
    rt, calls = make_runtime("done")
    data, _ = await run_case(rt, [DEBUG()] * 10)
    rs = roles_of(calls)
    assert rs.count("debugger") == A.MAX_REVIEW_CYCLES, rs
    assert rs.count("reviewer") == A.MAX_REVIEW_CYCLES + 1, rs
    assert data.get("status") == "review_limit", data
    # 마지막 debugger의 retry_count가 승격 임계(3) 이상인지
    debugger_retries = [rc for r, rc in calls if r == "debugger"]
    assert debugger_retries[-1] >= 3, debugger_retries
    assert "남은 문제" in data.get("content", ""), data
    print("Case C (반복 실패→review_limit, Pro 승격): OK", rs, "retries", debugger_retries)

    # Case D — 중단: reviewer가 cancelled 반환
    def cancel_status(role, n):
        return "cancelled" if role == "reviewer" else "done"
    rt, calls = make_runtime(cancel_status)
    data, _ = await run_case(rt, [DEBUG(), D()])
    assert data.get("status") == "cancelled", data
    print("Case D (중단): OK", data.get("status"))

    # Case E — context limit: reviewer가 context_blocked 반환
    def ctx_status(role, n):
        return "context_blocked" if role == "reviewer" else "done"
    rt, calls = make_runtime(ctx_status)
    data, _ = await run_case(rt, [DEBUG(), D()])
    assert data.get("status") == "context_blocked", data
    print("Case E (context limit): OK", data.get("status"))

    # Case F — CHAT triage: planner/coder/reviewer 호출 안 함
    rt, calls = make_runtime("done")
    async def chat_triage(all_messages):
        return "chat", 0, 0
    rt._triage = chat_triage
    set_tasks([D()])
    events = []
    await rt.run([{"role": "user", "content": "고마워"}], lambda e: _collect(events, e), "s1", None)
    assert roles_of(calls) == ["chat"], roles_of(calls)
    print("Case F (CHAT fast path): OK", roles_of(calls))

    print("\n모든 케이스 통과 ✓")


async def _collect(lst, e):
    lst.append(e)


if __name__ == "__main__":
    asyncio.run(main())
