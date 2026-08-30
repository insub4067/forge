"""P0-B: 게이트 검증 명령이 워크스페이스를 변경하면(자기충족 우회) 감지해 unavailable 강등한다.

_worktree_git_hash가 검증 전후 워크스페이스 변경을 잡는지 검증한다(무LLM·무샌드박스). git repo가
아니거나 실패하면 None(감지 불가). 실제 강등은 verify_gates에서 이 해시 비교로 이뤄진다.

실행: cd backend && python -m pytest test_gate_isolation.py -q
"""
import asyncio
import os
import subprocess
import tempfile

from app.runtime.verification import (
    _worktree_git_hash,
    make_prechange_worktree,
    remove_prechange_worktree,
)


def _init_repo():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "t"], check=True)
    with open(os.path.join(d, "a.txt"), "w") as f:
        f.write("orig\n")
    subprocess.run(["git", "-C", d, "add", "."], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "init"], check=True)
    return d


def test_hash_detects_verification_modifying_source():
    """검증 명령이 기존 소스를 수정하면(게이트 A가 B의 통과조건을 만드는 경로) 해시가 바뀐다."""
    d = _init_repo()
    h1 = asyncio.run(_worktree_git_hash(d))
    with open(os.path.join(d, "a.txt"), "w") as f:   # 검증 명령이 파일을 바꾼 상황
        f.write("modified by verify\n")
    h2 = asyncio.run(_worktree_git_hash(d))
    assert h1 is not None and h2 is not None and h1 != h2


def test_hash_detects_new_file_creation():
    """검증 명령이 새 파일을 만든 경우도 감지."""
    d = _init_repo()
    h1 = asyncio.run(_worktree_git_hash(d))
    with open(os.path.join(d, "planted.txt"), "w") as f:
        f.write("x\n")
    h2 = asyncio.run(_worktree_git_hash(d))
    assert h1 != h2


def test_hash_stable_when_verification_only_reads():
    """검증이 관찰만 하면(파일 변경 없음) 해시는 그대로 → passed 판정을 막지 않는다."""
    d = _init_repo()
    h1 = asyncio.run(_worktree_git_hash(d))
    subprocess.run(["git", "-C", d, "status"], capture_output=True)   # read-only
    h2 = asyncio.run(_worktree_git_hash(d))
    assert h1 == h2


def test_hash_none_for_non_git_workspace():
    """git repo가 아니면 None(감지 불가) — verify_gates는 이때 강등하지 않고 classify_gate로."""
    d = tempfile.mkdtemp()
    assert asyncio.run(_worktree_git_hash(d)) is None
    assert asyncio.run(_worktree_git_hash("")) is None


# ── P0-A: pre-change probe 워크트리 ──────────────────────────────────────
def test_prechange_worktree_is_head_excluding_run_changes():
    """probe 워크트리는 HEAD(변경 이전) 상태 — 이번 run의 uncommitted 변경을 제외한다.
    이 위에서 게이트를 돌려 '변경 전에도 통과 = trivial'을 판별한다(P0-A)."""
    d = _init_repo()   # a.txt = "orig\n" 커밋됨
    with open(os.path.join(d, "a.txt"), "w") as f:   # 이번 run의 변경(uncommitted)
        f.write("run change\n")
    tmp = asyncio.run(make_prechange_worktree(d))
    assert tmp is not None
    with open(os.path.join(tmp, "a.txt")) as f:
        assert f.read() == "orig\n"    # run 변경이 빠진 HEAD 상태
    asyncio.run(remove_prechange_worktree(d, tmp))
    assert not os.path.exists(tmp)


def test_prechange_worktree_none_for_non_git():
    """git repo가 아니면 None → probe 생략(trivial 강등 안 함, 안전)."""
    assert asyncio.run(make_prechange_worktree(tempfile.mkdtemp())) is None
    assert asyncio.run(make_prechange_worktree("")) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PASS — gate verification isolation (P0-A + P0-B)")


# ── P0-A telemetry: 판별력 라벨은 3값 ───────────────────────────────────────
def _validity(probe_res, expected="OK", probe_out="OK"):
    """verify_gates가 붙이는 gate_validity 라벨 규칙(그 자리의 식과 동일).
    probe를 못 돌렸으면(None) 'valid'가 아니라 'unknown'이다."""
    from app.runtime.verification import classify_gate
    trivial = probe_res is not None and classify_gate(probe_res[0], probe_res[1], expected)[0] == "passed"
    return "unknown" if probe_res is None else ("trivial" if trivial else "valid")


def test_gate_validity_label_is_three_valued():
    """probe 불가를 'valid'로 적으면 검증 유효성을 과대평가한다 — 모르는 것은 모른다고 남긴다."""
    assert _validity(None) == "unknown"                 # git 아님·워크트리 실패
    assert _validity((0, "OK")) == "trivial"            # 변경 전에도 통과 = 판별력 없음
    assert _validity((1, "boom")) == "valid"            # 변경 전엔 실패 = 변경을 판별함
    assert _validity((0, "다른 출력")) == "valid"        # exit 0이어도 기대 문자열 없으면 통과 아님
