"""스크립트형 테스트를 pytest에서도 돌린다.

아래 파일들은 `def test_*`가 하나도 없어 `pytest -q`가 **조용히 건너뛴다**. 이름이
test_*.py라 수집되는 것처럼 보이는 게 함정이다 — 실제로 이 사각 때문에 multi-agent
루프(`test_agent_mode_loop.py`)를 깨뜨린 채 커밋한 적이 있다. pytest 한 번으로
전부 돌게 묶어 재발을 막는다.

전부 LLM 없이 도는 결정적 테스트다(합계 ~9초). 실패하면 그 스크립트의 출력을 그대로 보여준다.
"""
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
]


def test_no_uncollected_script_suites():
    """`def test_*` 없는 test_*.py가 새로 생기면 목록에 넣으라고 알린다."""
    known = set(SCRIPT_SUITES) | {Path(__file__).name}
    orphans = []
    for p in sorted(HERE.glob("test_*.py")):
        if p.name in known:
            continue
        body = p.read_text(encoding="utf-8")
        if "\ndef test_" not in body and "\nasync def test_" not in body:
            orphans.append(p.name)
    assert not orphans, f"pytest가 건너뛰는 스크립트 테스트: {orphans} — SCRIPT_SUITES에 추가하세요"


@pytest.mark.parametrize("script", SCRIPT_SUITES)
def test_script_suite(script):
    r = subprocess.run([sys.executable, script], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"{script} 실패:\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}"
