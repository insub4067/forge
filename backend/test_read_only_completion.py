"""Read-only 완료 판정 회귀 테스트(무LLM·무샌드박스, 순수 함수).

핵심: 완료 판정 authority는 **실제 Git/filesystem 변경(run_changed)** — 명령 문자열 분류가 아니다.
write/edit뿐 아니라 bash sed·rm·mv·git commit 등 어떤 경로의 변경도 놓치지 않아야 false_completion=0
불변식이 유지된다. 조회(git status/log/rg/ls/read)는 변경 없음이므로 completed가 되어야 한다.

실행: cd backend && python -m pytest test_read_only_completion.py -q
"""
import hashlib

from app.runtime.completion_policy import (
    is_read_only_completion,
    worktree_run_changes,
    resolve_completion_verification,
)


def _sig(porcelain, diff=""):
    h = hashlib.sha1((porcelain + "\x00" + diff).encode("utf-8", "replace")).hexdigest()
    return {"porcelain": porcelain, "hash": h}


def _ro(intent="", run_changed=False, attempted=False, used_tools=True):
    return is_read_only_completion(intent, run_changed, attempted, used_tools)


# ── worktree_run_changes: 실제 변경 판정 ──────────────────────────────────
def test_case1_git_status_readonly_no_change():
    """Case 1: Task IR 실패 + git status 실행 → 변경 없음 → read-only completed."""
    clean = _sig("")
    changed, files = worktree_run_changes(clean, clean)
    assert changed is False and files == []
    assert _ro(intent="", run_changed=changed) is True


def test_case2_bash_file_create_is_mutation():
    """Case 2: Task IR 실패 + bash로 파일 생성(untracked) → mutation 탐지."""
    before, after = _sig(""), _sig("?? new_script.py\n")
    changed, files = worktree_run_changes(before, after)
    assert changed is True and "new_script.py" in files
    assert _ro(intent="", run_changed=changed) is False


def test_case3_sed_inplace_modify_is_mutation():
    """Case 3: Task IR 실패 + sed -i 수정(tracked 내용 변경) → mutation 탐지.
    porcelain status(' M')는 같아도 diff 내용이 달라 hash가 바뀐다."""
    before = _sig(" M app/foo.py\n", diff="@@ -1 +1 @@\n-a\n+a\n")
    after = _sig(" M app/foo.py\n", diff="@@ -1 +1 @@\n-a\n+bXYZ\n")
    changed, _ = worktree_run_changes(before, after)
    assert changed is True
    assert _ro(intent="", run_changed=changed) is False


def test_case4_file_delete_is_mutation():
    """Case 4: Task IR 실패 + 파일 삭제 → mutation 탐지."""
    before, after = _sig(""), _sig(" D app/gone.py\n", diff="deleted")
    changed, files = worktree_run_changes(before, after)
    assert changed is True and "app/gone.py" in files
    assert _ro(intent="", run_changed=changed) is False


def test_case5_preexisting_dirty_no_run_change_not_misattributed():
    """Case 5: 기존 dirty 파일 존재하지만 run 중 추가 변경 없음 → 이번 run 변경으로 오판 안 함."""
    dirty = _sig(" M ROOM_MEMORY.md\n", diff="@@ user edit @@")
    changed, files = worktree_run_changes(dirty, dirty)   # before==after
    assert changed is False and files == []                # 기존 dirty는 run 변경 아님
    assert _ro(intent="question", run_changed=changed) is True


def test_case6_preexisting_dirty_modified_more_is_detected():
    """Case 6: 기존 dirty 파일에 run 중 추가 수정 → mutation 탐지(같은 status여도 diff로 잡힘)."""
    before = _sig(" M ROOM_MEMORY.md\n", diff="@@ user edit @@")
    after = _sig(" M ROOM_MEMORY.md\n", diff="@@ user edit @@\n+run edit")
    changed, _ = worktree_run_changes(before, after)
    assert changed is True
    assert _ro(intent="question", run_changed=changed) is False


def test_case7_write_edit_failure_keeps_attempted_mutation():
    """Case 7: write/edit 호출(실패 포함) → attempted_mutation 유지 → read-only 아님."""
    assert _ro(intent="", run_changed=False, attempted=True) is False
    # net 변경이 없어도(원복/실패) attempted면 mutation 정책.


def test_case8_no_tool_evidence_not_completed():
    """Case 8: 도구 실행 없이 모델이 완료 주장 → read-only completed 금지."""
    assert _ro(intent="question", run_changed=False, used_tools=False) is False
    assert _ro(intent="", run_changed=False, used_tools=False) is False


def test_case9_non_git_workspace_safe_downgrade():
    """Case 9: git이 아닌 workspace(signature None) → 감지 불가 → 안전 강등(read-only 아님)."""
    changed, files = worktree_run_changes(None, None)
    assert changed is None and files == []
    assert _ro(intent="question", run_changed=None) is False   # completed_unverified로 강등


def test_case10_mutation_then_reverted_defined():
    """Case 10: mutation 했다가 원복 → net 변경 없음(run_changed False)이나 attempted면 mutation 정책.
    정책: write/edit로 원복해도 attempted_mutation이 남아 completed로 승격하지 않는다(안전)."""
    clean = _sig("")
    changed, _ = worktree_run_changes(clean, clean)   # net 원복 → 변경 없음
    assert changed is False
    assert _ro(intent="", run_changed=changed, attempted=True) is False


def test_case11_bash_git_commit_side_effect_detected():
    """Case 11: bash로 git add/commit → dirty→clean 전이가 signature에 잡혀 변경으로 탐지된다."""
    before = _sig(" M app/x.py\n", diff="@@ change @@")   # 커밋 전 dirty
    after = _sig("", diff="")                              # 커밋 후 clean
    changed, _ = worktree_run_changes(before, after)
    assert changed is True                                 # side effect 놓치지 않음
    assert _ro(intent="", run_changed=changed) is False


def test_case12_temp_cache_file_conservative_not_false_complete():
    """Case 12: 조회 중 임시·캐시 파일 생성 → 변경으로 보여 completed_unverified(안전 강등).
    오탐이지만 방향은 안전(false_completion 아님) — completed로 오판하지 않는다."""
    before, after = _sig(""), _sig("?? .cache/tmp123\n")
    changed, _ = worktree_run_changes(before, after)
    assert changed is True
    assert _ro(intent="question", run_changed=changed) is False   # 안전: completed 아님


# ── read-only intent 분류 (evidence 있을 때) ──────────────────────────────
def test_readonly_intents_complete_when_no_change():
    for intent in ("question", "investigation", "review", "conversation", "", "other"):
        assert _ro(intent=intent, run_changed=False) is True


def test_code_change_intent_no_change_stays_unverified():
    """code_change 요청인데 변경 없음 → read-only로 승격 안 함(수정 요청인데 안 함 = 미검증)."""
    assert _ro(intent="code_change", run_changed=False) is False


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
    print("PASS — read-only completion (git-evidence)")
