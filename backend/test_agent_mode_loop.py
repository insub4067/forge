"""에이전트 모드(단일/멀티) 오케스트레이션 결정적 검증.

LLM/네트워크 없이 _run_role·store를 목킹해 run()의 모드 분기만 검증한다.
- auto + simple → single(Developer 1회)
- auto + complex → multi(Planner→Developer→Reviewer)
- 사용자 명시(multi/single)가 auto 판정보다 우선
- Reviewer FAIL → Developer 1회 재수정(리뷰 루프 상한)
- Planner 실패 → 올인원 Developer로 안전 폴백
실행: python test_agent_mode_loop.py
"""
import asyncio

from app.runtime import agent as A


def make_runtime(dev_status="done", review_status="done", review_text="PASS",
                 planner_status="done", route_kind="code"):
    rt = A.AgentRuntime()
    calls = []  # (role, escalate, has_plan)

    async def fake_run_role(role, all_messages, send, session_id, ws, state,
                            recent_calls, step_base, room_memory="", retry_count=0,
                            tools=None, skills="", complexity="normal", escalate=False, has_image=False,
                            plan="", persist=True):
        has_plan = bool(plan)
        calls.append((role, escalate, has_plan))
        if role == "developer":
            state["files_changed"].append("app.py")  # 정상 구현 run(변경 있음)
        if role == "planner":
            st = planner_status(role, len(calls)) if callable(planner_status) else planner_status
            if st == "done":
                all_messages.append({"role": "assistant",
                                     "content": "## 계획\n1. 구현\n2. 검증\n## 완료 조건\n- 테스트 통과"})
            return st, 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}
        if role == "reviewer":
            st = review_status(role, len(calls)) if callable(review_status) else review_status
            all_messages.append({"role": "assistant", "content": review_text})
            return st, 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}
        # developer
        st = dev_status(role, len(calls), escalate) if callable(dev_status) else dev_status
        all_messages.append({"role": "assistant", "content": "작업 완료"})
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
    A.store.list_tasks = lambda *a, **k: _empty()
    A.store.replace_tasks = lambda *a, **k: _noop()
    A.store.list_gates = lambda *a, **k: _empty()
    A.store.replace_gates = lambda *a, **k: _noop()
    A.store.save_gate_result = lambda *a, **k: _noop()
    return rt, calls


async def _noop():
    return None


async def _empty():
    return []


async def run_case(rt, calls, msg="작업"):
    events = []

    async def emit(evt):
        events.append(evt)

    await rt.run([{"role": "user", "content": msg}], emit, "s1", None)
    done = [e for e in events if e["type"] == "done"]
    mode_evt = [e for e in events if e["type"] == "agent_mode"]
    mode = mode_evt[-1]["data"]["mode"] if mode_evt else None
    return (done[-1]["data"] if done else {}), mode, [r for r, _, _ in calls], calls


def plan_flags(calls):
    return [hp for _, _, hp in calls]


async def main():
    # Case A — auto + simple: single 경로, developer 1회, plan 없음
    rt, calls = make_runtime()
    data, mode, roles, all_calls = await run_case(rt, calls)
    assert mode == "single", mode
    assert roles == ["developer"], roles
    assert plan_flags(all_calls) == [False], plan_flags(all_calls)
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case A (auto+simple → single): OK", roles)

    # Case B — auto + complex(설계 키워드): multi, planner가 세운 계획이 developer에 전달
    rt, calls = make_runtime()
    data, mode, roles, all_calls = await run_case(rt, calls, msg="기존 모듈을 설계에 따라 리팩토링해줘")
    assert mode == "multi", mode
    assert roles == ["planner", "developer", "reviewer"], roles
    assert plan_flags(all_calls) == [False, True, False], plan_flags(all_calls)  # developer만 plan 보유
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case B (auto+complex → multi, plan 전달): OK", roles)

    # Case C — multi + Reviewer FAIL: developer가 1회 재수정(리뷰 루프 1회 상한)
    #   (항상 auto — 복잡도 키워드로 multi 경로를 유도)
    rt, calls = make_runtime(review_text="FAIL: calc.py에 하드코딩 발견")
    data, mode, roles, all_calls = await run_case(rt, calls, msg="모듈을 설계에 따라 리팩토링해줘")
    assert mode == "multi", mode
    assert roles == ["planner", "developer", "reviewer", "developer"], roles
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case C (Reviewer FAIL → 1회 재수정): OK", roles)

    # Case D — multi + Reviewer PASS: 재수정 없음
    rt, calls = make_runtime()
    data, mode, roles, _ = await run_case(rt, calls, msg="아키텍처를 리팩토링해줘")
    assert roles == ["planner", "developer", "reviewer"], roles
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case D (Reviewer PASS → 재수정 없음): OK", roles)

    # Case D2 — FAIL 본문에 'pass' 단어가 있어도 FAIL로 판정(마지막 줄만 본다).
    #   전체 부분검색이면 여기서 PASS로 뒤집혀 재수정을 건너뛰는 버그가 난다.
    rt, calls = make_runtime(review_text="FAIL: 경계 테스트를 pass하지 못함")
    data, mode, roles, _ = await run_case(rt, calls, msg="설계에 따라 리팩토링해줘")
    assert roles == ["planner", "developer", "reviewer", "developer"], roles
    print("Case D2 (FAIL 본문에 pass 포함 → 여전히 FAIL): OK", roles)

    # Case E — simple 요청은 복잡도 키워드가 없으면 single(항상 auto 판정)
    rt, calls = make_runtime()
    data, mode, roles, _ = await run_case(rt, calls, msg="간단한 작업")
    assert mode == "single", mode
    assert roles == ["developer"], roles
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case E (simple → single): OK", roles)

    # Case F — multi + Planner 실패: 올인원 Developer로 안전 폴백
    rt, calls = make_runtime(planner_status="max_steps")
    data, mode, roles, _ = await run_case(rt, calls, msg="설계에 따라 리팩토링해줘")
    assert roles == ["planner", "developer"], roles
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case F (Planner 실패 → Developer 폴백): OK", roles)

    # Case G — multi + Developer 막힘: 승격 루프(plan 유지) 후 Reviewer로 진행
    def stuck_then_ok(role, n, escalate):
        return "done" if escalate else "max_steps"
    rt, calls = make_runtime(dev_status=stuck_then_ok)
    data, mode, roles, all_calls = await run_case(rt, calls, msg="설계에 따라 리팩토링해줘")
    assert roles == ["planner", "developer", "developer", "reviewer"], roles
    assert plan_flags(all_calls) == [False, True, True, False], plan_flags(all_calls)
    assert data.get("status") in ("completed", "completed_unverified"), data
    print("Case G (multi+승격 루프, plan 유지): OK", roles)

    # Case H — multi + Developer 최종 실패: 실패 종료
    rt, calls = make_runtime(dev_status="max_steps")
    data, mode, roles, _ = await run_case(rt, calls, msg="설계에 따라 리팩토링해줘")
    assert roles == ["planner", "developer", "developer", "developer"], roles  # 1+MAX_ESCALATIONS(2)
    assert data.get("status") == "max_steps", data
    print("Case H (multi+최종 실패 → 종료): OK", roles)

    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
