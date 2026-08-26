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
def _make_run_rt(gates, verify_states, recovery_gates=None, recovery_raises=False,
                 dev_changes_files=True, roles=None):
    """run()을 LLM 없이 돌린다. recovery_gates가 주어지면 gate 복구 턴이 그 gate를 등록한다.

    recovery_raises=True면 복구 턴이 예외를 던진다(복구 실패가 run을 깨뜨리지 않는지 확인).
    dev_changes_files=False면 Developer가 파일을 바꾸지 않는다(변경 0건 semantics).
    """
    rt = A.AgentRuntime()
    commits = []
    verify_calls = []
    gates_state = [dict(g) for g in gates]
    role_calls = roles if roles is not None else []
    recovery_ctx = []

    async def fake_run_role(role, all_messages, send, session_id, ws, state,
                            recent_calls, step_base, room_memory="", retry_count=0,
                            tools=None, skills="", complexity="normal", escalate=False,
                            has_image=False, plan="", requirements="", persist=True):
        role_calls.append(role)
        if role == "gate_recovery":
            recovery_ctx.append(all_messages)
            # 복구 턴은 gate 등록 도구만 받는다(코드 수정 도구 없음) — 계약을 테스트에서 고정.
            names = {t["function"]["name"] for t in (tools or [])}
            assert names == {"update_gates"}, names
            if recovery_raises:
                raise RuntimeError("복구 턴 실패")
            if recovery_gates:
                gates_state[:] = [dict(g) for g in recovery_gates]
            return "done", 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}
        if role == "developer" and dev_changes_files:
            state["files_changed"].append("app.py")
        return "done", 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}
    rt._run_role = fake_run_role
    rt._recovery_ctx = recovery_ctx

    async def fake_triage(all_messages):
        return "code", 0, 0
    rt._triage = fake_triage

    async def fake_verify(ws, send, stage="generic"):
        verify_calls.append(1)
        idx = min(len(verify_calls) - 1, len(verify_states) - 1)
        return verify_states[idx]  # (state, report) 튜플 그대로

    rt._verify = fake_verify

    async def fake_autocommit(ws, goal, send, files, push=True):
        commits.append({"files": list(files), "push": push})
        return True, push
    rt._autocommit = fake_autocommit

    async def noop(*a, **k):
        return None
    rt._finalize_tasks = noop
    rt._mark_testing = noop
    rt._reflect = noop
    # task_ir 기본값이 ON이어도 이 런타임 테스트는 인터프리터를 타지 않는다 — 테스트가
    # 직접 주입한 _task_ir_reqs가 authoritative여야 하고, 실제 adapter 호출도 막는다.
    rt._maybe_interpret = noop

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
    assert commits != [], commits  # completed_unverified는 로컬 커밋 대상
    assert commits[0]["push"] is False, "completed_unverified는 push 금지(P0-3)"
    print("run(partial gate): OK — completed_unverified + 미완료 gate 명시 + NO push")


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
    assert commits[0]["push"] is True, "completed는 commit+push(P0-3)"
    print("run(all passed): OK — 전부 통과 시 completed + push")



async def _run_events(rt, msg="작업"):
    events = []

    async def emit(evt):
        events.append(evt)
    await rt.run([{"role": "user", "content": msg}], emit, "s1", None)
    return events


def _done(events):
    d = [e for e in events if e["type"] == "done"]
    return d[-1]["data"] if d else {}


def _cov(events):
    c = [e["data"] for e in events if e["type"] == "gate_coverage"]
    return c[-1] if c else {}


_G = {"title": "0으로 나누면 ValueError", "verification_method": "echo ok",
      "expected_result": "ok"}


async def test_case_a_gated_all_pass_completed():
    """A — 코드 변경 + gate 존재 + 전부 PASS → completed."""
    roles = []
    rt, commits, _ = _make_run_rt([_gate(1, "로그인", "echo ok", "ok")],
                                  verify_states=[("passed", "v1"), ("passed", "v2")],
                                  roles=roles)
    ev = await _run_events(rt)
    assert _done(ev).get("status") == "completed", _done(ev)
    assert "gate_recovery" not in roles, roles     # gate가 있으면 복구하지 않는다
    assert _cov(ev)["coverage"] == "gated", _cov(ev)
    assert commits and commits[0]["push"] is True
    print("Case A (gate 있음 + 전부 PASS → completed): OK")


async def test_case_b_recovered_gate_pass_completed():
    """B — gate 0으로 시작 → 복구가 gate 생성 → gate PASS → completed."""
    roles = []
    rt, commits, _ = _make_run_rt([], verify_states=[("passed", "v1"), ("passed", "v2")],
                                  recovery_gates=[_gate(1, "0 나눗셈", "echo ok", "ok")],
                                  roles=roles)
    ev = await _run_events(rt)
    assert _done(ev).get("status") == "completed", _done(ev)
    assert roles.count("gate_recovery") == 1, roles
    assert _cov(ev)["coverage"] == "recovered_gated", _cov(ev)
    # 복구 컨텍스트는 최소여야 한다 — Developer transcript 재전송 금지
    ctx = rt._recovery_ctx[0]
    assert len(ctx) == 1 and ctx[0]["role"] == "user", ctx
    assert "app.py" in ctx[0]["content"]
    print("Case B (gate 0 → 복구 생성 → PASS → completed): OK")


async def test_case_c_recovery_fails_to_create_completed_unverified():
    """C — 복구 후에도 gate 0 → generic PASS여도 completed_unverified.

    이번 작업의 핵심 invariant: 코드 변경 + gate 0에서 completed는 나오지 않는다.
    generic verification은 "기존 test/build가 안 깨졌다"만 말한다."""
    roles = []
    rt, commits, _ = _make_run_rt([], verify_states=[("passed", "v1"), ("passed", "v2")],
                                  recovery_gates=None, roles=roles)
    ev = await _run_events(rt)
    d = _done(ev)
    assert d.get("status") == "completed_unverified", d
    assert roles.count("gate_recovery") == 1, roles
    assert _cov(ev)["coverage"] == "generic_only", _cov(ev)
    # 미검증 사실을 침묵하지 않는다
    assert "요구사항 게이트 없음" in d.get("content", ""), d
    # 미검증은 로컬 commit만 — origin push 금지
    assert commits and commits[0]["push"] is False, commits
    print("Case C (복구 후에도 gate 0 → completed_unverified, push 금지): OK")


async def test_case_d_no_change_keeps_semantics():
    """D — 변경 없음 + gate 0 → 기존 no-change semantics 유지(복구 안 함)."""
    roles = []
    rt, commits, _ = _make_run_rt([], verify_states=[("passed", "v1")],
                                  dev_changes_files=False, roles=roles)
    ev = await _run_events(rt)
    d = _done(ev)
    assert d.get("status") == "completed_unverified", d
    assert "코드 변경 없이" in d.get("content", ""), d
    assert "gate_recovery" not in roles, roles   # 바꾼 게 없으면 gate도 필요 없다
    assert commits == [], commits
    assert _cov(ev)["coverage"] == "no_change", _cov(ev)
    print("Case D (변경 없음 → 복구 안 함, 기존 semantics): OK")


async def test_case_e_recovery_exception_does_not_crash_run():
    """E — 복구 턴이 예외를 던져도 run이 죽지 않고 안전 상태로 마감한다."""
    roles = []
    rt, commits, _ = _make_run_rt([], verify_states=[("passed", "v1"), ("passed", "v2")],
                                  recovery_raises=True, roles=roles)
    ev = await _run_events(rt)
    d = _done(ev)
    assert d.get("status") == "completed_unverified", d
    assert roles.count("gate_recovery") == 1, roles
    assert _cov(ev)["coverage"] == "generic_only", _cov(ev)
    print("Case E (복구 예외 → crash 없이 completed_unverified): OK")


async def test_case_f_recovery_runs_at_most_once():
    """F — gate 복구는 두 번 이상 돌지 않는다(비용 상한).

    gate 실패 → Developer 수리 루프를 타는 경로에서도 복구가 재진입하지 않아야 한다."""
    roles = []
    rt, _commits, _ = _make_run_rt(
        [], verify_states=[("passed", "v1"), ("passed", "v2"), ("passed", "v3")],
        recovery_gates=[_gate(1, "실패하는 요구사항", "exit 1", "never")], roles=roles)
    await _run_events(rt)
    assert roles.count("gate_recovery") == 1, roles
    print("Case F (복구 최대 1회): OK")


def test_resolve_completion_verification_invariant():
    """gate 없는 코드 변경은 completed가 될 수 없다 — 순수 함수로 고정."""
    r = A.resolve_completion_verification
    assert r("none", "passed") == "completed_unverified"
    assert r("none", "unavailable") == "completed_unverified"
    assert r("passed", "passed") == "completed"
    assert r("passed", "unavailable") == "completed_unverified"
    assert r("partial", "passed") == "completed_unverified"
    assert r("unavailable", "passed") == "completed_unverified"
    # gate 없음은 실패가 아니다
    assert "failed" not in r("none", "passed")
    # Task IR requirement 미검증(traceability gap)이면 gate/verify가 다 통과해도 completed 아님.
    assert r("passed", "passed", True) == "completed_unverified"
    assert r("passed", "passed", False) == "completed"   # 기본값은 기존 동작


def test_needs_gate_recovery_scope():
    """gate가 필요 없는 요청에는 복구를 걸지 않는다(억지 gate 금지)."""
    n = A.needs_gate_recovery
    assert n("code", ["a.py"], 0) is True
    assert n("code", ["a.py"], 2) is False   # 이미 gate 있음
    assert n("code", [], 0) is False         # 변경 없음(설명·조회·리뷰)
    assert n("chat", ["a.py"], 0) is False   # 작업 run 아님


def test_coverage_kind_categories():
    k = A._coverage_kind
    assert k(0, [], False, False) == "not_applicable"
    assert k(0, [], False, True) == "no_change"
    assert k(0, ["a.py"], True, True) == "generic_only"
    assert k(2, ["a.py"], False, True) == "gated"
    assert k(2, ["a.py"], True, True) == "recovered_gated"


async def test_run_requirement_gap_downgrades():
    """Task IR requirement가 gate로 검증되지 않으면 completed로 나가지 않는다(강등).

    gate 자체는 통과했지만 그 gate가 어떤 requirement에도 연결되지 않은 상황 —
    "빌드·테스트는 통과했는데 사용자가 요구한 것은 확인 안 됨"이 false_completion이다.
    """
    gates = [_gate(1, "로그인", "echo ok", "ok")]          # requirement_id 없음
    rt, commits, _ = _make_run_rt(gates, verify_states=[("passed", "v1"), ("passed", "v2")])
    rt._task_ir_reqs["s1"] = [{"id": "R1", "text": "다크모드 토글"}]
    data = await _run_rt(rt)
    assert data.get("status") == "completed_unverified", data
    assert commits != [], commits                          # 강등이지 차단이 아니다(로컬 커밋은 함)
    assert commits[0]["push"] is False, "미검증 요구사항은 push 금지"
    # 무엇이 미검증인지 보고에 드러난다(사유만 말하고 대상을 숨기지 않는다).
    assert "다크모드 토글" in data.get("content", ""), data
    print("run(requirement gap): OK — 강등 + NO push + 미검증 요구사항 명시")


async def test_run_requirement_traced_stays_completed():
    """requirement가 passed gate로 이어지면 강등하지 않는다(false-block 방지)."""
    g = _gate(1, "다크모드", "echo ok", "ok")
    g["requirement_id"] = "R1"
    rt, commits, _ = _make_run_rt([g], verify_states=[("passed", "v1"), ("passed", "v2")])
    rt._task_ir_reqs["s1"] = [{"id": "R1", "text": "다크모드 토글"}]
    data = await _run_rt(rt)
    assert data.get("status") == "completed", data
    assert commits[0]["push"] is True, "검증된 완료는 기존대로 push"
    assert "미검증" not in data.get("content", ""), data
    print("run(requirement traced): OK — 강등 없음 + push")


def test_requirements_block_gives_ids_to_model():
    """requirement id를 프롬프트에 실제로 넣어야 gate가 연결될 수 있다(빈 입력은 무동작)."""
    block = A._requirements_block([{"id": "R1", "text": "다크모드 토글"},
                                   {"id": "R2", "text": ""},        # 빈 텍스트는 제외
                                   {"text": "id 없음"}])            # id 없으면 제외
    assert block == "- R1: 다크모드 토글", block
    assert A._requirements_block(None) == ""
    assert A._requirements_block([]) == ""
    # Task IR off(빈 블록)면 system 프롬프트가 바뀌지 않는다.
    assert A._system_for("developer") == A._system_for("developer", requirements="")
    assert "R1" in A._system_for("developer", requirements=block)
    print("requirements_block: OK — id 주입, off면 프롬프트 불변")


def test_untraced_requirements_maps_ids_to_text():
    u = A._untraced_requirements([{"id": "R1", "text": "다크모드"}],
                                 {"unverified_ids": ["R1", "R9"]})
    assert u == [{"id": "R1", "text": "다크모드"}, {"id": "R9", "text": ""}], u
    assert A._untraced_requirements([], None) == []
    assert A._untraced_requirements([], {"unverified_ids": []}) == []


async def main():
    test_clamp_gate_status()
    await test_case_a_gated_all_pass_completed()
    await test_case_b_recovered_gate_pass_completed()
    await test_case_c_recovery_fails_to_create_completed_unverified()
    await test_case_d_no_change_keeps_semantics()
    await test_case_e_recovery_exception_does_not_crash_run()
    await test_case_f_recovery_runs_at_most_once()
    test_resolve_completion_verification_invariant()
    test_needs_gate_recovery_scope()
    test_coverage_kind_categories()
    test_schedule_no_same_file_in_batch()
    await test_verify_gates()
    await test_run_gate_fail_no_commit()
    await test_run_partial_gate_honest()
    await test_run_integration_fail_blocks()
    await test_run_gate_all_passed_completed()
    await test_run_requirement_gap_downgrades()
    await test_run_requirement_traced_stays_completed()
    test_requirements_block_gives_ids_to_model()
    test_untraced_requirements_maps_ids_to_text()
    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())

