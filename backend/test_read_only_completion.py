"""Read-only 작업의 completion semantics 회귀 테스트(무LLM·무샌드박스, 순수 함수).

핵심: 조회·설명·리뷰(read-only)는 독립 verification이 NOT_APPLICABLE이므로 성공 시 completed가
되어야 한다. '부분 완료 · 미검증'이 아니다. 단 false_completion=0 불변식은 유지 — intent가
read-only여도 실제 파일 변경이 있으면 mutation 정책으로 폴백한다.

실행: cd backend && python -m pytest test_read_only_completion.py -q
"""
from app.runtime.completion_policy import (
    is_read_only_completion,
    resolve_completion_verification,
    READ_ONLY_INTENTS,
)


def test_case1_git_status_read_only_completed():
    """Case 1: 'git 상태 알려줘' — investigation, 변경 없음 → NOT_APPLICABLE → completed."""
    assert is_read_only_completion("investigation", []) is True


def test_case2_recent_commits_read_only_completed():
    """Case 2: '최근 커밋 알려줘' — question/investigation, 변경 없음 → completed."""
    assert is_read_only_completion("question", []) is True


def test_case3_explain_readme_read_only_completed():
    """Case 3: 'README 설명해줘' — question, read_file 성공, 변경 없음 → completed."""
    assert is_read_only_completion("question", []) is True


def test_case4_project_structure_read_only_completed():
    """Case 4: '프로젝트 구조 알려줘' — investigation, 변경 없음 → completed."""
    assert is_read_only_completion("investigation", []) is True
    assert is_read_only_completion("review", []) is True
    assert is_read_only_completion("conversation", []) is True


def test_case5_mutation_uses_verification_policy():
    """Case 5: 'foo.py 수정해줘' — code_change → read-only 아님 → 기존 verification 정책."""
    assert is_read_only_completion("code_change", []) is False
    assert is_read_only_completion("code_change", ["foo.py"]) is False
    # 모호(other)도 mutation 정책 유지(안전 방향).
    assert is_read_only_completion("other", []) is False


def test_case6_mixed_read_and_mutation_uses_verification():
    """Case 6: 'git 확인하고 foo.py 수정' — mutation이 존재하면 verification 정책.
    Task IR intent가 code_change로 잡히거나(혼합→작업), 혹은 read-only로 잡혀도 실제 변경이
    있으면 files_changed로 폴백해 mutation 정책을 탄다."""
    assert is_read_only_completion("code_change", ["README.md"]) is False
    # intent가 read-only로 오분류돼도 실제 파일 변경이 있으면 read-only 완료로 승격 안 됨.
    assert is_read_only_completion("question", ["README.md"]) is False


def test_case7_read_only_but_mutated_does_not_false_complete():
    """Case 7(false_completion 방지 핵심): read-only intent인데 실제 코드가 바뀌었다면
    completed로 오판하지 않는다 — files_changed가 있으면 무조건 mutation 정책."""
    for intent in READ_ONLY_INTENTS:
        assert is_read_only_completion(intent, ["a.py"]) is False


def test_reliability_invariant_mutation_policy_unchanged():
    """기존 mutation 완료 정책(false_completion=0 불변식)은 그대로다."""
    # gate+generic 둘 다 통과만 completed.
    assert resolve_completion_verification("passed", "passed") == "completed"
    # gate 없음 → completed_unverified(완전검증 아님).
    assert resolve_completion_verification("none", "passed") == "completed_unverified"
    # requirement_gap → 강등.
    assert resolve_completion_verification("passed", "passed", requirement_gap=True) \
        == "completed_unverified"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PASS — read-only completion semantics")
