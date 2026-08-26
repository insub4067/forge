"""사용자가 명시한 6개 reliability invariant를 한 곳에서 결정적으로 보호한다(무LLM·무샌드박스).

세부 케이스는 test_acceptance_gates(완료 판정)·test_gate_infra_error(P2)·test_reliability_gates(P1)에
흩어져 있으나, 이 파일은 "6개 invariant가 전부 지켜진다"를 순수 함수 단언으로 한눈에 고정한다.
가장 중요한 것은 #6 — false_completion 방지가 success rate보다 우선한다.

실행: cd backend && python -m pytest test_reliability_six_invariants.py -q
"""
from app.runtime.completion_policy import resolve_completion_verification
from app.runtime.verification import classify_gate, _gate_infra_error


def test_inv1_no_evidence_no_verified_completion():
    """#1 verification evidence 없는 작업은 verified completion(completed)이 될 수 없다."""
    # gate 없음(none) → 어떤 generic 상태여도 completed 아님.
    assert resolve_completion_verification("none", "passed") == "completed_unverified"
    assert resolve_completion_verification("none", "unavailable") == "completed_unverified"
    # generic만 통과하고 gate가 없으면 completed 아님.
    assert resolve_completion_verification("none", "passed") != "completed"


def test_inv2_failed_requirement_blocks_completion():
    """#2 failed requirement(gate)가 있으면 completed가 될 수 없다."""
    # gstate가 passed가 아니면(failed/partial/unavailable) 절대 completed 아님.
    for gstate in ("failed", "partial", "unavailable"):
        assert resolve_completion_verification(gstate, "passed") == "completed_unverified"
    # requirement_gap(Task IR requirement 미검증)도 completed를 막는다.
    assert resolve_completion_verification("passed", "passed", requirement_gap=True) \
        == "completed_unverified"


def test_inv3_gate_infra_vs_implementation_failure():
    """#3 gate 인프라 오류(명령 결함)와 구현 실패(로직 실패)를 구분한다."""
    # 명령 자체 인프라 오류 → unavailable(GATE_EXECUTION_ERROR), failed 아님.
    v, r = classify_gate(127, "bash: pyton3: command not found", "PASS")
    assert v == "unavailable" and "GATE_EXECUTION_ERROR" in r
    v, r = classify_gate(1, '  File "<string>", line 1\nSyntaxError: invalid syntax', "PASS")
    assert v == "unavailable" and "GATE_EXECUTION_ERROR" in r
    # 진짜 구현 실패(assertion/기대값 불일치) → 여전히 failed(검증 약화 안 됨).
    assert classify_gate(1, "AssertionError: expected 100 got 0", "PASS")[0] == "failed"
    assert classify_gate(0, "FAIL", "PASS")[0] == "failed"


def test_inv4_verification_does_not_pollute_next_verification():
    """#4 verification 실행 자체가 이후 verification 결과를 오염시키지 않는다.
    (스냅샷/청소 배선은 test_reliability_gates가 실제 _verify 이중검증으로 커버 —
    여기서는 청소 함수가 검증-생성 파일만 지우고 기존 파일을 보존함을 단언.)"""
    import os
    import tempfile
    from app.runtime.agent import AgentRuntime
    d = tempfile.mkdtemp()
    open(os.path.join(d, "impl.py"), "w").close()          # 구현 산출물(스냅샷에 포함)
    before = AgentRuntime._verify_snapshot(d)
    open(os.path.join(d, "state.json"), "w").close()       # 검증이 만든 잔존 파일
    AgentRuntime._verify_cleanup(d, before)
    assert os.path.exists(os.path.join(d, "impl.py"))      # 기존 파일 보존
    assert not os.path.exists(os.path.join(d, "state.json"))  # 검증-생성 파일만 제거


def test_inv5_duplicate_execution_made_idempotent():
    """#5 동일 verification command의 의도치 않은 중복 실행이 결과를 바꾸지 않는다.
    청소로 인해 두 번째 실행이 첫 번째의 잔존 상태를 보지 않는다(멱등) — 새 파일 없으면 no-op."""
    import os
    import tempfile
    from app.runtime.agent import AgentRuntime
    d = tempfile.mkdtemp()
    open(os.path.join(d, "keep.py"), "w").close()
    before = AgentRuntime._verify_snapshot(d)
    # 아무 새 파일도 안 만든 실행 → 청소는 no-op → 기존 동작과 동일(멱등의 자명 경계).
    AgentRuntime._verify_cleanup(d, before)
    assert os.path.exists(os.path.join(d, "keep.py"))
    assert AgentRuntime._verify_snapshot(d) == before


def test_inv6_false_completion_prevention_over_success_rate():
    """#6 false_completion 방지가 success rate보다 우선한다.
    애매하면 completed로 승격하지 않고 completed_unverified(안전)로 남긴다."""
    # gate 인프라 오류는 unavailable → completed_unverified(강등), completed 아님.
    assert resolve_completion_verification("unavailable", "passed") == "completed_unverified"
    # 검사 대상 코드의 SyntaxError(파일 경로)는 infra로 오분류하지 않는다 → failed 유지
    # (깨진 코드가 completed_unverified로 새어 false_completion이 늘지 않게).
    assert not _gate_infra_error(1, 'File "acct.py", line 3\nSyntaxError: invalid syntax')
    # 완전 검증(gate passed + generic passed + requirement 충족)만 completed.
    assert resolve_completion_verification("passed", "passed") == "completed"


if __name__ == "__main__":
    test_inv1_no_evidence_no_verified_completion()
    test_inv2_failed_requirement_blocks_completion()
    test_inv3_gate_infra_vs_implementation_failure()
    test_inv4_verification_does_not_pollute_next_verification()
    test_inv5_duplicate_execution_made_idempotent()
    test_inv6_false_completion_prevention_over_success_rate()
    print("PASS — 6 reliability invariants 보호됨")
