"""grep 도구가 이벤트 루프를 막거나 폭주하지 않는지 검증 (LLM 없음).

실제 사고: 워크스페이스가 /Users/insub(홈 전체)였고, grep이 모델이 준 path를 무시하고
워크스페이스 전체를 동기 재귀로 훑어 CPU 95%로 이벤트 루프를 몇 분간 블록 → 서버 먹통.

실행: python test_grep_bounds.py  (pytest로도 수집된다)
"""
import asyncio
import os
import tempfile

from app.tools import registry


def test_grep_respects_given_path():
    """모델이 지정한 path 안에서만 찾는다(워크스페이스 전체로 확장 금지)."""
    with tempfile.TemporaryDirectory() as ws:
        os.makedirs(os.path.join(ws, "sub"))
        open(os.path.join(ws, "sub", "a.py"), "w").write("needle here\n")
        open(os.path.join(ws, "other.py"), "w").write("needle here\n")
        out, _ = asyncio.run(registry.execute_tool(
            "grep", {"pattern": "needle", "path": "sub"}, ws))
        assert "sub/a.py" in out or "a.py" in out
        assert "other.py" not in out


def test_grep_caps_hits():
    """결과 수 상한(_GREP_MAX_HITS)을 넘지 않는다."""
    with tempfile.TemporaryDirectory() as ws:
        for i in range(50):
            open(os.path.join(ws, f"f{i}.txt"), "w").write("hit\n" * 20)
        out, _ = asyncio.run(registry.execute_tool("grep", {"pattern": "hit", "path": "."}, ws))
        assert out.count("\n") <= registry._GREP_MAX_HITS + 2  # +tail 안내줄


def test_grep_stops_at_file_budget():
    """파일 방문 상한이 재귀를 멈춘다(폭주 방지)."""
    with tempfile.TemporaryDirectory() as ws:
        # 상한보다 많은 non-matching 파일을 둬도 예산에서 멈춘다
        for i in range(100):
            open(os.path.join(ws, f"n{i}.txt"), "w").write("nothing\n")
        budget = {"files": registry._GREP_MAX_FILES, "deadline": 1e18}
        found = []
        registry._grep(__import__("pathlib").Path(ws), "nothing", None, found, budget)
        assert found == []  # 예산 소진 상태면 한 파일도 안 읽는다


def test_grep_skips_symlink_loops():
    """심링크 루프에서 무한 재귀하지 않는다."""
    with tempfile.TemporaryDirectory() as ws:
        open(os.path.join(ws, "a.py"), "w").write("x\n")
        try:
            os.symlink(ws, os.path.join(ws, "loop"))  # 자기 자신을 가리키는 링크
        except OSError:
            return  # 심링크 불가 환경은 건너뜀
        out, _ = asyncio.run(registry.execute_tool("grep", {"pattern": "x", "path": "."}, ws))
        assert "a.py" in out  # 무한 루프 없이 완료


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("grep 경계 테스트 통과 ✓")


# ─── list_dir / read_file 자기보호 (grep과 같은 blast-radius 방어) ───

def test_list_dir_caps_entries_and_offloads():
    """list_dir이 거대 트리에서 항목 상한으로 멈추고 루프를 막지 않는다."""
    import pathlib
    with tempfile.TemporaryDirectory() as ws:
        for i in range(registry._LISTDIR_MAX_ENTRIES + 500):
            open(os.path.join(ws, f"f{i}.txt"), "w").close()
        out, _ = asyncio.run(registry.execute_tool("list_dir", {"path": "."}, ws))
        lines = out.splitlines()
        # 상한 + 안내줄 정도만(전부 나열하지 않는다)
        assert len(lines) <= registry._LISTDIR_MAX_ENTRIES + 2, len(lines)
        assert "항목 상한 도달" in out


def test_list_dir_skips_symlink_loops():
    with tempfile.TemporaryDirectory() as ws:
        os.makedirs(os.path.join(ws, "real"))
        open(os.path.join(ws, "real", "a.txt"), "w").close()
        try:
            os.symlink(ws, os.path.join(ws, "loop"))
        except OSError:
            return
        out, _ = asyncio.run(registry.execute_tool("list_dir", {"path": "."}, ws))
        assert "real/" in out  # 무한 루프 없이 완료


def test_read_file_caps_huge_file():
    """거대 파일은 통째로 읽지 않고 앞부분 + 안내만 준다."""
    with tempfile.TemporaryDirectory() as ws:
        big = os.path.join(ws, "big.log")
        with open(big, "wb") as f:
            f.write(b"x" * (registry._READ_FILE_MAX_BYTES + 1000))
        out, _ = asyncio.run(registry.execute_tool("read_file", {"path": "big.log"}, ws))
        assert "너무 큽니다" in out
        assert len(out) < registry._READ_FILE_MAX_BYTES + 500  # 통째로 안 실림


def test_read_file_normal_file_unaffected():
    with tempfile.TemporaryDirectory() as ws:
        open(os.path.join(ws, "s.py"), "w").write("print(1)\n")
        out, _ = asyncio.run(registry.execute_tool("read_file", {"path": "s.py"}, ws))
        assert "print(1)" in out and "너무 큽니다" not in out
