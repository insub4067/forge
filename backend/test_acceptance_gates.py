"""Acceptance Gate Ledger 검증 — 모델의 '완료' 선언을 신뢰하지 않고 프로세스가 증거로 판정.

LLM/네트워크 없이 결정적으로 확인한다:
  1) 모델은 passed/failed를 설정할 수 없다(클램프).
  2) _verify_gates: exit 0 + expected_result 일치일 때만 passed. 그 외는 정직하게
     failed/unavailable로 확정(거짓 PASS 금지).
  3) run() 흐름: 게이트 실패 → verification_failed(커밋 금지), 부분 통과 → completed_unverified.
  4) _verify_integration: 게이트 있으면 최종 회귀를 한 번 더 돌리고 실패 시 완료 금지.
  5) schedule: 같은 파일을 고치는 worker는 같은 배치에 들어가지 않는다.
실행: python test_acceptance_gates.py
"""
import asyncio
import os
import tempfile

from app.runtime import agent as A
from app.orchestrator import schedule as S


# ─────────────────────────────────────────────────────────────────────────────
# 순수 함수 / 클램프
# ─────────────────────────────────────────────────────────────────────────────
def test_clamp_gate_status():
    # passed/failed는 프로세스 전용 — 모델이 보내면 working으로 내린다.
    assert A._clamp_gate_status("passed") == "working"
    assert A._clamp_gate_status("failed") == "working"
    assert A._clamp_gate_status("pending") == "pending"
    assert A._clamp_gate_status("working") == "working"
    assert A._clamp_gate_status("blocked") == "blocked"
    assert A._clamp_gate_status("abandoned") == "abandoned"
    assert A._clamp_gate_status("unavailable") == "unavailable"
    # 정의되지 않은 상태도 working으로(임의 상태 차단).
    assert A._clamp_gate_status("done") == "working"
    print("clamp_gate_status: OK — passed/failed 차단, 정직 상태만 허용")


def test_schedule_no_same_file_in_batch():
    workers = [
        {"id": "w1", "files": ["a.py", "b.py"]},
        {"id": "w2", "files": ["b.py", "c.py"]},   # w1과 b.py 충돌
        {"id": "w3", "files": ["d.py"]},
        {"id": "w4", "files": ["a.py", "e.py"]},   # w1과 a.py 충돌
    ]
    assert S.conflicts(workers, max_parallel=2) == [], S.plan_schedule(workers, 2)
    # w2는 w1과 같은 배치에 들어가면 안 된다(파일 충돌 → 순차화).
    batches = S.plan_schedule(workers, max_parallel=2)
    assert batches[0][0] == "w1"
    assert "w2" not in batches[0], batches
    # 파일을 선언하지 않은 worker는 충돌 검사 대상이 아니다.
    noworker = [{"id": "x", "files": []}, {"id": "y", "files": []}]
    assert S.conflicts(noworker, max_parallel=2) == []
    print("schedule: OK — 같은 파일을 공유하는 worker는 같은 배치에 배치되지 않음")


# ─────────────────────────────────────────────────────────────────────────────
# _verify_gates 직접 검증(실제 subprocess 실행)
# ─────────────────────────────────────────────────────────────────────────────
def _gate(gid, title, method, expected, status="working", reason=None):
    return {"id": gid, "title": title, "verification_method": method,
            "expected_result": expected, "status": status, "failure_reason": reason}


async def _run_verify_gates(gates):
    rt = A.AgentRuntime()
    saved = []

    async def fake_list(sid):
        return [dict(g) for g in gates]

    async def fake_save(sid, gid, status, evidence, reason):
        saved.append((gid, status, evidence, reason))
        for g in gates:
            if g["id"] == gid:
                g["status"] = status
                g["evidence"] = evidence
                g["failure_reason"] = reason

    A.store.list_gates = fake_list
    A.store.save_gate_result = fake_save

    async def send(event_type, data):
        pass

    with tempfile.TemporaryDirectory() as d:
        state, report = await rt._verify_gates(d, "s1", send)
    return state, report, saved


async def test_verify_gates():
    # 1) exit 0 + expected 일치 → passed
    st, rep, saved = await _run_verify_gates([_gate(1, "로그인", "echo hello", "hello")])
    assert st == "passed", (st, rep)
    assert saved[0][1] == "passed", saved
    assert "exit_code" in saved[0][2], saved  # evidence에 실제 명령 결과 포함
    print("verify_gates(passed): OK — exit 0 + expected 일치만 passed")

    # 2) exit 0 + expected 불일치 → failed
    st, rep, _ = await _run_verify_gates([_gate(1, "로그인", "echo hi", "bye")])
    assert st == "failed", (st, rep)
    print("verify_gates(failed): OK — exit 0라도 expected 불일치면 failed")

    # 3) exit 0 + expected 없음 → unavailable(통과 증거로 불충분)
    st, rep, _ = await _run_verify_gates([_gate(1, "다크모드", "echo ok", "")])
    assert st == "unavailable", (st, rep)
    print("verify_gates(unavailable): OK — exit 0만으로는 PASS 오판 금지")

    # 4) 모델이 passed라고 주장해도 검증 방법 없으면 unavailable로 재확정(재실행·덮어쓰기)
    st, rep, _ = await _run_verify_gates(
        [_gate(1, "미구현", "", "", status="passed")])
    assert st == "unavailable", (st, rep)
    print("verify_gates(passed-주장 재검증): OK — 검증 방법 없으면 passed로 인정하지 않음")

    # 5) 부분 통과: 하나 passed + 하나 unavailable → partial(실패 0)
    st, rep, _ = await _run_verify_gates([
        _gate(1, "로그인", "echo ok", "ok"),
        _gate(2, "다크모드", "", ""),
    ])
    assert st == "partial", (st, rep)
    print("verify_gates(partial): OK — passed+미검증 = partial(정직 표기)")


# ─────────────────────────────────────────────────────────────────────────────
# run() 통합 흐름 — 게이트가 완료 판정을 바꾸는지
# ─────────────────────────────────────────────────────────────────────────────
def _make_run_rt(gates, verify_states):
    rt = A.AgentRuntime()
    commits = []
    verify_calls = []
    gates_state = [dict(g) for g in gates]

    async def fake_run_role(role, all_messages, send, session_id, ws, state,
                            recent_calls, step_base, room_memory="", retry_count=0,
                            tools=None, skills="", complexity="normal", escalate=False,
                            has_image=False, plan=""):
        if role == "developer":
            state["files_changed"].append("app.py")
        return "done", 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}
    rt._run_role = fake_run_role

    async def fake_triage(all_messages):
        return "code", 0, 0
    rt._triage = fake_triage

    async def fake_verify(ws, send):
        verify_calls.append(1)
        idx = min(len(verify_calls) - 1, len(verify_states) - 1)
        return verify_states[idx]  # (state, report) 튜플 그대로

    rt._verify = fake_verify

    async def fake_autocommit(ws, goal, send, files):
        commits.append(list(files))
    rt._autocommit = fake_autocommit

    async def noop(*a, **k):
        return None
    rt._finalize_tasks = noop
    rt._mark_testing = noop
    rt._reflect = noop

    async def fake_list_gates(sid):
        return [dict(g) for g in gates_state]

    async def fake_replace_gates(sid, gs):
        gates_state[:] = gs

    async def fake_save_gate_result(sid, gid, status, evidence, reason):
        for g in gates_state:
            if g["id"] == gid:
                g["status"] = status
                g["evidence"] = evidence
                g["failure_reason"] = reason

    A.store.list_gates = fake_list_gates
    A.store.replace_gates = fake_replace_gates
    A.store.save_gate_result = fake_save_gate_result
    A.store.save_agent_run = noop
    A.store.update_context_usage = noop
    A.store.ensure_session = noop
    A.store.save_history = noop
    A.store.set_session_final_status = noop
    A.store.list_tasks = lambda *a, **k: _empty()
    A.store.replace_tasks = noop
    A.eventlog.record = lambda *a, **k: None
    A.eventlog.tail = lambda *a, **k: []
    return rt, commits, verify_calls


async def _empty():
    return []


async def _run_rt(rt):
    events = []

    async def emit(evt):
        events.append(evt)

    await rt.run([{"role": "user", "content": "작업"}], emit, "s1", None)
    done = [e for e in events if e["type"] == "done"]
    return done[-1]["data"] if done else {}


async def test_run_gate_fail_no_commit():
    gates = [_gate(1, "로그인", "exit 1", "x")]
    rt, commits, _ = _make_run_rt(gates, verify_states=[("passed", "v1"), ("passed", "v2")])
    data = await _run_rt(rt)
    assert data.get("status") == "verification_failed", data
    assert commits == [], commits  # 검증 실패는 커밋 금지(invariant)
    print("run(gate fail): OK — 게이트 실패 시 verification_failed + 커밋 금지")


async def test_run_partial_gate_honest():
    gates = [
        _gate(1, "로그인", "echo ok", "ok"),
        _gate(2, "다크모드", "", ""),  # 검증 방법 없음 → unavailable
    ]
    rt, commits, _ = _make_run_rt(gates, verify_states=[("passed", "v1"), ("passed", "v2")])
    data = await _run_rt(rt)
    assert data.get("status") == "completed_unverified", data
    # 미완료 gate를 조용히 생략하지 않는다(정직 표기).
    assert "다크모드" in data.get("content", ""), data
    assert commits != [], commits  # completed_unverified는 커밋 대상
    print("run(partial gate): OK — 부분 통과는 completed_unverified + 미완료 gate 명시")


async def test_run_integration_fail_blocks():
    gates = [_gate(1, "로그인", "echo ok", "ok")]
    # generic 통과 → gate 통과 → integration(generic 재실행) 실패
    rt, commits, _ = _make_run_rt(gates, verify_states=[("passed", "v1"), ("failed", "v2")])
    data = await _run_rt(rt)
    assert data.get("status") == "verification_failed", data
    assert commits == [], commits
    print("run(integration fail): OK — 최종 회귀 실패 시 완료 금지")


async def test_run_gate_all_passed_completed():
    gates = [_gate(1, "로그인", "echo ok", "ok")]
    rt, commits, _ = _make_run_rt(gates, verify_states=[("passed", "v1"), ("passed", "v2")])
    data = await _run_rt(rt)
    assert data.get("status") == "completed", data
    assert commits != [], commits
    print("run(all passed): OK — 전부 통과 시 completed")


async def main():
    test_clamp_gate_status()
    test_schedule_no_same_file_in_batch()
    await test_verify_gates()
    await test_run_gate_fail_no_commit()
    await test_run_partial_gate_honest()
    await test_run_integration_fail_blocks()
    await test_run_gate_all_passed_completed()
    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
