"""스크립트형 테스트를 pytest에서도 돌린다.

아래 파일들은 `def test_*`가 하나도 없어 `pytest -q`가 **조용히 건너뛴다**. 이름이
test_*.py라 수집되는 것처럼 보이는 게 함정이다 — 실제로 이 사각 때문에 multi-agent
루프(`test_agent_mode_loop.py`)를 깨뜨린 채 커밋한 적이 있다. pytest 한 번으로
전부 돌게 묶어 재발을 막는다.

전부 LLM 없이 도는 결정적 테스트다(합계 ~9초). 실패하면 그 스크립트의 출력을 그대로 보여준다.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

SCRIPT_SUITES = [
    "test_agent_mode_loop.py",      # Planner→Developer→Reviewer 경로
    "test_developer_loop.py",
    "test_reliability_gates.py",
    "test_skills_scope.py",
    "test_task_facade_images.py",
    "test_sandbox_timeout.py",
    "test_bench_quality.py",
    "test_mcp_server.py",
    # pytest가 수집하는 test_*도 있지만 main()의 invariant 본체는 스크립트로만 돈다 —
    # 그래서 아래 orphan 검사(def test_ 유무)에 걸리지 않고 조용히 빠져 있었다.
    "test_reliability_invariants.py",
    "test_acceptance_gates.py",
]


def test_no_uncollected_script_suites():
    """pytest가 실행하지 않는 테스트 본체가 있으면 목록에 넣으라고 알린다.

    두 가지를 잡는다.
    1) `def test_*`가 아예 없는 파일 — pytest가 통째로 건너뛴다.
    2) `def test_*`는 있지만 `if __name__ == "__main__"`으로만 도는 main() 본체가 있는 파일 —
       수집되는 테스트가 하나라도 있으면 (1)에 걸리지 않아 조용히 빠진다(실제로 빠져 있었다).
    """
    known = set(SCRIPT_SUITES) | {Path(__file__).name}
    orphans = []
    for p in sorted(HERE.glob("test_*.py")):
        if p.name in known:
            continue
        body = p.read_text(encoding="utf-8")
        has_pytest_tests = "\ndef test_" in body or "\nasync def test_" in body
        runs_own_main = "async def main(" in body or "\ndef main(" in body
        if not has_pytest_tests or runs_own_main:
            orphans.append(p.name)
    assert not orphans, f"pytest가 실행하지 않는 테스트 본체: {orphans} — SCRIPT_SUITES에 추가하세요"


@pytest.mark.parametrize("script", SCRIPT_SUITES)
def test_script_suite(script):
    # 스크립트는 conftest.py를 타지 않는다 — 운영 로그 격리를 env로 직접 넘긴다.
    env = {**os.environ, "FORGE_LOG_DIR": os.environ.get("FORGE_LOG_DIR", "")}
    r = subprocess.run([sys.executable, script], cwd=HERE, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"{script} 실패:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}"
