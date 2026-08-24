"""자동 커밋은 에이전트가 바꾼 파일만 담는다 (실제 git 저장소로 검증, LLM 없음).

실제 사고: 읽기 전용 요청("프로젝트 구조 파악해줘", "최신 커밋 확인해봐")인데도
`git add -A`가 사람이 편집 중이던 미커밋 변경을 에이전트 커밋으로 담아 push했다.
서로 다른 저장소에서 2건 발생했다.

실행: python test_autocommit_scope.py  (pytest로도 수집된다)
"""
import asyncio
import os
import subprocess
import tempfile

from app.runtime import agent as A


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True).stdout.strip()


def _repo():
    d = tempfile.mkdtemp(prefix="forge-autocommit-")
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    open(os.path.join(d, "seed.txt"), "w").write("seed\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "seed")
    return d


async def _commit(ws, paths):
    rt = A.AgentRuntime()
    events = []

    async def send(t, d):
        events.append((t, d))
    await rt._autocommit(ws, "테스트 작업", send, paths)
    return events


def test_only_agent_paths_are_committed():
    d = _repo()
    open(os.path.join(d, "agent.py"), "w").write("에이전트가 만든 파일\n")
    open(os.path.join(d, "human.py"), "w").write("사람이 편집 중인 파일\n")
    asyncio.run(_commit(d, ["agent.py"]))
    files = _git(d, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["agent.py"], files
    assert "human.py" in _git(d, "status", "--porcelain")   # 사람 변경은 그대로 남는다


def test_no_paths_means_no_commit():
    d = _repo()
    open(os.path.join(d, "human.py"), "w").write("사람이 편집 중인 파일\n")
    before = _git(d, "rev-parse", "HEAD")
    asyncio.run(_commit(d, []))          # 읽기 전용 run — 바꾼 파일이 없다
    assert _git(d, "rev-parse", "HEAD") == before
    asyncio.run(_commit(d, None))
    assert _git(d, "rev-parse", "HEAD") == before


def test_staged_human_change_is_not_swept_in():
    d = _repo()
    open(os.path.join(d, "human.py"), "w").write("사람이 stage해 둔 변경\n")
    _git(d, "add", "human.py")           # 사람이 이미 stage해 둔 상태
    open(os.path.join(d, "agent.py"), "w").write("에이전트 변경\n")
    asyncio.run(_commit(d, ["agent.py"]))
    assert _git(d, "show", "--name-only", "--format=", "HEAD").split() == ["agent.py"]


def test_absolute_path_and_outside_path():
    d = _repo()
    open(os.path.join(d, "agent.py"), "w").write("에이전트 변경\n")
    # 모델이 절대경로를 줘도 처리하고, 워크스페이스 밖 경로는 무시한다.
    asyncio.run(_commit(d, [os.path.join(d, "agent.py"), "/etc/hosts"]))
    assert _git(d, "show", "--name-only", "--format=", "HEAD").split() == ["agent.py"]


def test_deleted_file_is_committed():
    d = _repo()
    os.remove(os.path.join(d, "seed.txt"))
    asyncio.run(_commit(d, ["seed.txt"]))
    assert _git(d, "show", "--name-only", "--format=", "HEAD").split() == ["seed.txt"]
    assert "seed.txt" not in _git(d, "ls-files")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: OK")
    print("\n자동 커밋 범위 통과 ✓")


async def _outcome(ws, paths):
    async def send(t, d):
        pass
    return await A.AgentRuntime()._autocommit(ws, "테스트 작업", send, paths)


def test_autocommit_returns_real_outcome():
    """_autocommit은 실제 commit 결과를 돌려준다 — 완료 리포트가 추측하지 않게."""
    ws = _repo()
    open(os.path.join(ws, "a.txt"), "w").write("x")
    assert asyncio.run(_outcome(ws, ["a.txt"])) == (True, False)   # 원격 없음 → push 실패
    assert asyncio.run(_outcome(ws, ["a.txt"])) == (False, False)  # 변경 없음 → 커밋 안 함
    assert asyncio.run(_outcome(ws, [])) == (False, False)         # 대상 없음


def test_report_never_claims_unearned_push():
    """push가 실패했으면 성공으로 보고하지 않는다 (false completion 방지).
    최종 보고는 _autocommit이 돌려준 실제 (committed, pushed)로 만들어진다."""
    def line(status, committed, pushed):
        return A.AgentRuntime.format_completion_summary({
            "status": status, "gate_state": "passed", "generic_verification": "passed",
            "integration_verification": "passed", "files_changed_count": 2,
            "verified_requirements": [], "unverified_requirements": [],
            "failed_requirements": [], "commit_status": committed, "push_status": pushed})

    assert "commit·push 완료" in line("completed", True, True)
    assert "push 실패" in line("completed", True, False)
    assert "push 안 함" in line("completed_unverified", True, False)
    assert "commit 안 됨" in line("completed", False, False)
    for bad in (line("completed", True, False), line("completed", False, False),
                line("completed_unverified", True, False)):
        assert "push 완료" not in bad
