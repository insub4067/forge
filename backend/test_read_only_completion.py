"""Read-only 작업의 completion semantics 회귀 테스트(무LLM·무샌드박스, 순수 함수).

핵심: 조회·설명·리뷰(read-only)는 독립 verification이 NOT_APPLICABLE이므로 성공 시 completed가
되어야 한다('부분 완료 · 미검증' 아님). 판정은 Task IR intent 단독이 아니라 **실행 evidence**
(files_changed·attempted_mutation·used_tools)로 하여 Task IR가 flaky해도(intent="") 동작한다.
단 false_completion=0 불변식은 유지 — 실제/시도된 mutation은 mutation 정책으로 폴백.

실행: cd backend && python -m pytest test_read_only_completion.py -q
"""
from app.runtime.completion_policy import (
    is_read_only_completion,
    resolve_completion_verification,
    READ_ONLY_INTENTS,
)


def _ro(intent, files=None, attempted=False, used_tools=True):
    return is_read_only_completion(intent, files or [], attempted, used_tools)


def test_case1_git_status_read_only_completed():
    """Case 1: 'git 상태 알려줘' — investigation, bash 도구, 변경/편집 없음 → completed."""
    assert _ro("investigation") is True


def test_case2_recent_commits_read_only_completed():
    """Case 2: '최근 커밋 알려줘' — question, 조회 성공 → completed."""
    assert _ro("question") is True


def test_case3_explain_readme_read_only_completed():
    """Case 3: 'README 설명해줘' — question, read_file 성공 → completed."""
    assert _ro("question") is True


def test_case4_project_structure_read_only_completed():
    """Case 4: '프로젝트 구조 알려줘' — investigation/review → completed."""
    assert _ro("investigation") is True
    assert _ro("review") is True
    assert _ro("conversation") is True


def test_case5_mutation_uses_verification_policy():
    """Case 5: 'foo.py 수정해줘' — code_change → read-only 아님 → verification 정책."""
    assert _ro("code_change") is False
    assert _ro("code_change", files=["foo.py"]) is False


def test_case6_mixed_read_and_mutation_uses_verification():
    """Case 6: 'git 확인하고 foo.py 수정' — 실제 파일 변경이 있으면 verification 정책."""
    assert _ro("code_change", files=["README.md"]) is False
    assert _ro("question", files=["README.md"]) is False


def test_case7_attempted_mutation_does_not_false_complete():
    """Case 7(false_completion 방지): write/edit 도구를 썼으면(변경이 안 남았어도) read-only 아님."""
    for intent in list(READ_ONLY_INTENTS) + ["", "other", "code_change"]:
        assert _ro(intent, attempted=True) is False


def test_case8_task_ir_failed_still_read_only():
    """Task IR interpreter가 None(intent="")이어도, 편집·변경 없이 도구만 실행했으면 read-only.
    (flaky Task IR에도 git 조회가 '부분 완료'로 떨어지지 않게 하는 핵심.)"""
    assert _ro("") is True
    assert _ro("other") is True


def test_case9_no_tool_evidence_not_completed():
    """도구 실행 evidence가 없으면(LLM self-report만) read-only completed로 오판하지 않는다."""
    assert _ro("question", used_tools=False) is False
    assert _ro("", used_tools=False) is False


def test_reliability_invariant_mutation_policy_unchanged():
    """기존 mutation 완료 정책(false_completion=0 불변식)은 그대로다."""
    assert resolve_completion_verification("passed", "passed") == "completed"
    assert resolve_completion_verification("none", "passed") == "completed_unverified"
    assert resolve_completion_verification("passed", "passed", requirement_gap=True) \
        == "completed_unverified"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PASS — read-only completion semantics")
