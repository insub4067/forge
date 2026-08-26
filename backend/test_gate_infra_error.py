"""Gate 인프라-오류 분류 회귀 — 명령 자체의 결함(SyntaxError·command-not-found 등)으로
gate가 실패하면 `failed`가 아니라 `unavailable`(GATE_EXECUTION_ERROR)로 분류되는지,
그리고 **진짜 구현 실패(AssertionError·기대값 불일치)는 여전히 `failed`**로 잡혀 검증이
약화되지 않는지 결정적으로 확인한다(LLM/네트워크/샌드박스 없음).

실행: python -m pytest test_gate_infra_error.py -q
"""
from app.runtime.completion_policy import resolve_completion_verification
from app.runtime.verification import classify_gate


def test_infra_error_maps_to_unavailable_not_failed():
    """(a) 명령 자체가 인프라 오류로 실패하면 failed가 아니라 unavailable."""
    # 실측 사례: python3 -c에 여러 줄을 리터럴 \n으로 넣어 개행이 안 풀림.
    syntax = "  File \"<string>\", line 1\n    try:\\n    withdraw()\n         ^\nSyntaxError: invalid syntax"
    verdict, reason = classify_gate(1, syntax, "PASS")
    assert verdict == "unavailable", (verdict, reason)
    assert "GATE_EXECUTION_ERROR" in reason

    for out in (
        "bash: python33: command not found",
        "python3: can't open file 'test_acct.py': [Errno 2] No such file or directory",
        "  File \"<string>\", line 1\nIndentationError: unexpected indent",  # -c 인라인 들여쓰기
        "bash: -c: line 1: unexpected EOF while looking for matching `\"'",
        "bash: line 1: syntax error near unexpected token `)'",
    ):
        v, r = classify_gate(127, out, "PASS")
        assert v == "unavailable", (out, v)
        assert "GATE_EXECUTION_ERROR" in r


def test_code_syntax_error_stays_failed():
    """(b') **false_completion 방지 핵심**: 검사 대상 코드(워크스페이스 .py)의 SyntaxError는
    infra가 아니라 진짜 구현 실패다. traceback이 파일 경로면 failed로 남긴다 — 깨진 코드가
    completed_unverified로 새어 false_completion이 늘지 않게."""
    # 모델이 문법 깨진 코드를 작성 → gate가 그걸 import → traceback이 워크스페이스 파일.
    code_syntax = ("Traceback (most recent call last):\n"
                   "  File \"acct.py\", line 3\n    def withdraw(\n"
                   "                 ^\nSyntaxError: invalid syntax")
    v, r = classify_gate(1, code_syntax, "PASS")
    assert v == "failed", (v, r)  # <string> 아님 → 코드 결함 → failed 유지


def test_real_assertion_failure_still_failed():
    """(b) 진짜 구현 실패(assertion/기대값 불일치)는 여전히 failed — 검증 약화 안 됨."""
    # 명령은 정상 실행됐고(exit 1) 출력은 AssertionError — 로직 실패다.
    assert_out = "Traceback (most recent call last):\n  File \"t.py\", line 3\nAssertionError: expected 100 got 0"
    v, r = classify_gate(1, assert_out, "PASS")
    assert v == "failed", (v, r)

    # rc==0인데 기대 문자열 미발견(구현이 틀려 FAIL을 찍음)도 failed로 남는다.
    v2, _ = classify_gate(0, "FAIL", "PASS")
    assert v2 == "failed", v2

    # "SyntaxError"가 출력에 없는 일반 exit 1 실패도 failed.
    v3, _ = classify_gate(1, "AssertionError: 잔액이 음수", "PASS")
    assert v3 == "failed", v3


def test_normal_pass_no_regression():
    """(c) 정상 통과 회귀 없음."""
    v, r = classify_gate(0, "테스트 통과\nPASS\n", "PASS")
    assert v == "passed", (v, r)
    assert r == ""

    # expected 없으면 exit 0만으로 통과로 오판하지 않는다(기존 동작 유지).
    v2, _ = classify_gate(0, "done", "")
    assert v2 == "unavailable", v2


def test_unavailable_demotes_to_completed_unverified():
    """분류 개선이 완료 정책과 정합: gate가 unavailable이면 completed_unverified(강등)이지
    verification_failed도 completed도 아니다 — false_completion을 늘리지 않는다."""
    # 인프라 오류 gate는 집계에서 unavailable/partial이 된다(더 이상 "failed" 아님) →
    # gstate != "passed"라 completed_unverified로 강등. completed도 verification_failed도 아니다.
    assert resolve_completion_verification("unavailable", "passed") == "completed_unverified"
    assert resolve_completion_verification("partial", "passed") == "completed_unverified"
    # 대조: 정상 통과 gate만 있으면 completed. 인프라 오류를 이쪽으로 오분류하지 않는다.
    assert resolve_completion_verification("passed", "passed") == "completed"


if __name__ == "__main__":
    test_infra_error_maps_to_unavailable_not_failed()
    test_code_syntax_error_stays_failed()
    test_real_assertion_failure_still_failed()
    test_normal_pass_no_regression()
    test_unavailable_demotes_to_completed_unverified()
    print("PASS")
