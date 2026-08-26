"""Continual Harness Refinement 커널의 결정적 검증 (LLM·네트워크·DB 없음).

- 실패 서명 정규화: 경로·줄번호가 달라도 같은 실패는 같은 서명
- run 분할: 오래 사는 세션 안에서 done 기준으로 서로 다른 run을 센다
- 근거 요건: 서로 다른 run 2회 이상 반복돼야 후보가 생긴다(1회 관측 학습 금지)
- rollback 가능성: before/after를 함께 저장한다
- 결정 매핑: approve/ignore/rollback만 허용

실행: python test_refinement.py  (pytest로도 수집된다)
"""
from app.runtime import refine

PYTEST_FAIL_A = """[pytest (backend)] 테스트 실패 (exit 1):
FAILED test_login.py::test_token - AssertionError: expected 200 got 401
  File "/Users/insub/Desktop/forge/backend/test_login.py", line 42
"""
# 같은 실패인데 경로·줄번호만 다른 리포트(다른 run)
PYTEST_FAIL_B = """[pytest (backend)] 테스트 실패 (exit 1):
FAILED test_login.py::test_token - AssertionError: expected 200 got 401
  File "/home/ci/forge/backend/test_login.py", line 87
"""
BUILD_FAIL = """[npm run build (frontend)] 빌드 실패 (exit 2):
error TS2345: Argument of type 'string' is not assignable to parameter of type 'number'.
"""


def test_signature_normalizes_paths_and_line_numbers():
    assert refine.failure_signature(PYTEST_FAIL_A) == refine.failure_signature(PYTEST_FAIL_B)
    assert refine.failure_signature(PYTEST_FAIL_A) != refine.failure_signature(BUILD_FAIL)
    assert refine.failure_signature(PYTEST_FAIL_A).startswith("pytest (backend):")
    assert refine.failure_signature("") == "verification: "


def _events(*seq):
    """(type, report) 목록을 eventlog 행 모양으로."""
    return [{"session_id": "s1", "type": t,
             "data": ({"report": r} if r else {})} for t, r in seq]


def test_scan_failures_splits_runs_by_done():
    evs = _events(("verify_failed", PYTEST_FAIL_A), ("done", ""),
                  ("verify_failed", PYTEST_FAIL_B), ("done", ""))
    fails = refine.scan_failures(evs)
    assert [f["run"] for f in fails] == ["s1#0", "s1#1"]
    assert fails[0]["signature"] == fails[1]["signature"]


def test_same_run_twice_is_not_evidence():
    # 한 run 안에서 검증이 두 번 실패(최초+수리 후)해도 "반복"이 아니다.
    evs = _events(("verify_failed", PYTEST_FAIL_A), ("verify_failed", PYTEST_FAIL_A))
    fails = refine.scan_failures(evs)
    assert {f["run"] for f in fails} == {"s1#0"}
    assert refine.propose("s1#0", fails) is None


def test_first_occurrence_makes_no_candidate():
    fails = refine.scan_failures(_events(("verify_failed", PYTEST_FAIL_A)))
    assert refine.propose("s1#0", fails) is None


def test_repeat_across_runs_makes_candidate():
    evs = _events(("verify_failed", PYTEST_FAIL_A), ("done", ""),
                  ("verify_failed", PYTEST_FAIL_B))
    fails = refine.scan_failures(evs)
    c = refine.propose("s1#1", fails, evidence={"succeeded": True, "session_cost_usd": 0.01})
    assert c is not None
    assert c["type"] == "skill" and c["scope"] == "project"   # global 자동 오염 없음
    assert c["target"] == "verify-pytest-backend"
    assert c["evidence_runs"] == ["s1#0", "s1#1"]             # 근거 run 2개
    assert c["failure_pattern"] == refine.failure_signature(PYTEST_FAIL_A)
    assert c["evidence"]["session_cost_usd"] == 0.01
    assert c["before_text"] == "" and c["after_text"] == c["proposed_change"]


def test_before_snapshot_is_kept_for_rollback():
    evs = _events(("verify_failed", BUILD_FAIL), ("done", ""), ("verify_failed", BUILD_FAIL))
    c = refine.propose("s1#1", refine.scan_failures(evs), before="# 기존 skill\n내용\n")
    assert c["before_text"] == "# 기존 skill\n내용\n"
    assert c["after_text"].startswith("# 기존 skill")     # 덮어쓰지 않고 덧붙인다
    assert c["proposed_change"] in c["after_text"]
    assert c["target"] == "verify-npm-run-build-frontend"


def test_other_runs_failure_is_not_mine():
    # 이번 run이 실패하지 않았으면 다른 run의 실패로 후보를 만들지 않는다.
    evs = _events(("verify_failed", PYTEST_FAIL_A), ("done", ""), ("done", ""))
    assert refine.propose("s1#2", refine.scan_failures(evs)) is None


def test_decision_mapping_is_closed():
    from app.db import approvals
    assert approvals._DECISIONS == {"approve": "approved", "ignore": "ignored", "rollback": "pending"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: OK")
    print("\nrefinement 커널 통과 ✓")
