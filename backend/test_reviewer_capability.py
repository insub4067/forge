"""Reviewer capability 격리 — 프롬프트가 아니라 런타임 tool schema로 mutation을 차단하는지
결정적으로 확인한다(LLM/네트워크 없음).

- Reviewer: read 4종만, write/edit/bash/build/skill 없음.
- Developer: mutation 도구 유지.
- Planner: read-only 유지.
- 런타임 게이트(allowed_tools)는 스키마에 없는 도구를 하드 거부한다.
실행: python -m pytest test_reviewer_capability.py -q
"""
from app import agents
from app.runtime.agent import READ_ONLY_TOOLS, READ_ONLY_TOOL_SCHEMAS

_MUTATION = {"write_file", "edit_file", "bash", "build_frontend", "save_skill"}


def _names(role):
    return {t["function"]["name"] for t in agents._ROLE_TOOLS[role]}


def test_reviewer_is_read_only():
    rev = _names("reviewer")
    assert rev == READ_ONLY_TOOLS, rev                  # read_file/list_dir/grep/find_symbol만
    assert not (rev & _MUTATION), f"reviewer가 mutation 도구를 받음: {rev & _MUTATION}"


def test_reviewer_uses_shared_readonly_schema():
    # crew 메타(agents)와 런타임(_run_role에 넘기는 값)이 같은 상수여야 표시=실제가 보장된다.
    assert agents._ROLE_TOOLS["reviewer"] is READ_ONLY_TOOL_SCHEMAS


def test_developer_keeps_mutation_and_planner_readonly():
    dev = _names("developer")
    assert _MUTATION <= dev, f"developer가 mutation 도구를 잃음: {_MUTATION - dev}"
    assert _names("planner") == READ_ONLY_TOOLS


def test_reviewer_capability_badges_reflect_readonly():
    caps = agents._capabilities("reviewer")
    assert "Read Only" in caps and "Write" not in caps and "Bash" not in caps, caps
