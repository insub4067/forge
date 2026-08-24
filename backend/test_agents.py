"""Agent Roster / Crew catalog 검증 — Agent Definition이 실제 Runtime과 일치하는지.

LLM/네트워크 없이 결정적으로 확인한다:
  1) main roster가 실제 runtime이 호출하는 role만(developer/planner/reviewer/chat) 노출한다.
  2) role별 도구 목록이 실제 `_run_role`에 넘겨지는 tool schema와 일치한다.
  3) 모델·thinking·reasoning_effort가 ModelRouter policy와 일치한다.
  4) fresh_context가 실제 fresh 컨텍스트 생성(_planner_context/_reviewer_context)과 일치한다.
  5) prompt 응답이 docs/agents/*.md 원문 그대로다(dynamic context·secret 미포함).
  6) 없는 role은 404(API에서는 HTTPException, catalog에서는 None)다.
  7) 라이브 상태 연결: 실행 중인 role만 working, 아니면 idle/recent(허구 상태 금지).
실행: cd backend && ./.venv/bin/python -m pytest -q test_agents.py
"""
import os

from app import agents as A
from app.config import settings
from app.runtime import agent as R
from app.tools.registry import APPROVAL_REQUIRED, CHAT_TOOLS, TOOL_SCHEMAS
from app.orchestrator.model_router import ModelRouter


# ─────────────────────────────────────────────────────────────────────────────
# 1) 실제 Agent 목록
# ─────────────────────────────────────────────────────────────────────────────
def test_main_roster_only_real_roles():
    ids = [a["id"] for a in A.agent_definitions()]
    assert ids == ["developer", "planner", "reviewer", "chat"], ids
    # 모든 메인 에이전트는 실제 runtime이 호출하는 role이고 활성이다.
    for a in A.agent_definitions():
        assert a["active"] is True
        assert a["prompt_source"] == f"docs/agents/{a['id']}.md"
        # prompt 파일이 실제 존재해야 한다(없는 role을 활성으로 노출하지 않는다).
        assert (R.AGENTS_DIR / f"{a['id']}.md").exists(), a["id"]


def test_no_future_agents_as_active_cards():
    """미래 worker/가상 agent를 활성 카드로 노출하지 않는다."""
    for a in A.agent_definitions():
        assert "worker" not in a["id"].lower()
        assert a["id"] not in ("researcher", "frontend_worker", "backend_worker")


def test_internal_section_separate():
    internal_ids = [i["id"] for i in A.internal_definitions()]
    # gate_recovery/triage/vision은 내부 섹션으로 분리 — 메인 roster와 겹치지 않는다.
    assert "gate_recovery" in internal_ids and "triage" in internal_ids
    main_ids = {a["id"] for a in A.agent_definitions()}
    assert not (set(internal_ids) & main_ids)


# ─────────────────────────────────────────────────────────────────────────────
# 2) role별 도구 metadata가 실제 runtime과 일치
# ─────────────────────────────────────────────────────────────────────────────
def test_runtime_match_tools():
    # 실제 `_run_role`에 넘겨지는 스키마와 catalog 도구 목록이 일치해야 한다.
    expect = {
        "developer": sorted(t["function"]["name"] for t in TOOL_SCHEMAS),
        "planner": sorted(t["function"]["name"] for t in R.READ_ONLY_TOOL_SCHEMAS),
        "reviewer": sorted(t["function"]["name"] for t in TOOL_SCHEMAS),  # runtime 기본값
        "chat": sorted(t["function"]["name"] for t in CHAT_TOOLS),
    }
    for a in A.agent_definitions():
        assert sorted(a["tools"]) == expect[a["id"]], a["id"]
        assert a["tool_count"] == len(a["tools"])


def test_runtime_match_read_only():
    # read_only = role이 받는 스키마에 승인 필요 mutation 도구가 없는지, 실제와 일치.
    for a in A.agent_definitions():
        names = set(a["tools"])
        has_mutation = bool(names & APPROVAL_REQUIRED)
        assert a["read_only"] == (not has_mutation), a["id"]
    # 알려진 사실: developer는 mutation, planner·chat은 read-only.
    by_id = {a["id"]: a for a in A.agent_definitions()}
    assert by_id["developer"]["read_only"] is False
    assert by_id["planner"]["read_only"] is True
    assert by_id["chat"]["read_only"] is True


def test_runtime_match_model_policy():
    policy = ModelRouter().get_policy()["roles"]
    for a in A.agent_definitions():
        pol = policy[a["id"]]
        assert a["model"] == pol["model"], a["id"]
        assert a["thinking"] == bool(pol["thinking"]), a["id"]
        assert a["reasoning_effort"] == pol.get("reasoning_effort", ""), a["id"]
    # developer 승격 모델은 설정에서 온다.
    dev = next(a for a in A.agent_definitions() if a["id"] == "developer")
    assert dev["escalation_model"] == (settings.developer_pro_model
                                       or settings.deep_seek_model or "deepseek-v4-pro")


def test_runtime_match_fresh_context():
    # planner/reviewer는 실제로 fresh 컨텍스트를 만든다(_planner_context/_reviewer_context).
    # developer/chat은 전체 히스토리(persistent)를 받는다.
    by_id = {a["id"]: a for a in A.agent_definitions()}
    assert by_id["planner"]["fresh_context"] is True
    assert by_id["reviewer"]["fresh_context"] is True
    assert by_id["developer"]["fresh_context"] is False
    assert by_id["chat"]["fresh_context"] is False
    # 실제 컨텍스트 함수가 축소 컨텍스트를 만드는지까지 확인(설계가 아니라 동작 검증).
    fake = [{"role": "user", "content": f"m{i}"} for i in range(20)]
    planner_msgs = R._planner_context(fake, max_msgs=8)
    assert len(planner_msgs) == 8, "planner는 최근 8개만 받는다"
    reviewer_msgs = R._reviewer_context(fake, plan="계획")
    assert len(reviewer_msgs) == 5, "reviewer는 user 3 + plan + 지시 = 5개만 받는다"


# ─────────────────────────────────────────────────────────────────────────────
# 3) prompt가 실제 파일과 일치 + dynamic context/secret 미노출
# ─────────────────────────────────────────────────────────────────────────────
def test_prompt_file_match():
    for role in ("developer", "planner", "reviewer", "chat", "gate_recovery"):
        data = A.agent_prompt(role)
        assert data is not None, role
        expected = (R.AGENTS_DIR / f"{role}.md").read_text(encoding="utf-8")
        assert data["prompt"] == expected, f"{role} prompt가 실제 파일과 다르다"
        assert data["source"] == f"docs/agents/{role}.md"
        assert data["hash"] == A._prompt_hash(role)


def test_prompt_no_dynamic_context():
    """Base Role Prompt에 동적 user/memory 컨텍스트가 절대 섞이지 않는다."""
    dynamic_markers = (
        "전역 메모리 (GLOBAL_MEMORY.md)",
        "방 메모리 (ROOM_MEMORY.md)",
        "축적된 Skill",
        "외부 계획 (Planner가 수립",
        "이것은 검증된 작업에서 축적한",
    )
    for role in ("developer", "planner", "reviewer", "chat"):
        prompt = A.agent_prompt(role)["prompt"]
        for marker in dynamic_markers:
            assert marker not in prompt, f"{role} prompt에 dynamic context가 노출됨: {marker}"


def test_prompt_no_secret():
    """env secret 값·API key가 prompt/API 응답에 노출되지 않는다."""
    secret_candidates = [
        settings.deep_seek_api_key,
        os.environ.get("DEEPSEEK_API_KEY", ""),
        os.environ.get("FORGE_AUTH_TOKEN", ""),
    ]
    for role in ("developer", "planner", "reviewer", "chat"):
        data = A.agent_prompt(role)
        assert data is not None
        blob = data["prompt"] + data["source"] + str(data["hash"])
        for sec in secret_candidates:
            if sec and len(sec) >= 8:  # 빈 값·너무 짧은 값은 검사 의미 없음
                assert sec not in blob, f"{role} prompt에 secret 노출"
        # API 응답 키에도 secret 키 자체가 없어야 한다.
        for a in A.agent_definitions():
            keys = " ".join(str(k) for k in a.keys())
            assert "api_key" not in keys and "token" not in keys.lower(), "응답 키에 secret 포함"


# ─────────────────────────────────────────────────────────────────────────────
# 4) 존재하지 않는 role
# ─────────────────────────────────────────────────────────────────────────────
def test_unknown_role_not_found():
    assert A.agent_detail("ghost_agent") is None
    assert A.agent_prompt("ghost_agent") is None
    # vision/triage는 내부 섹션에만 있고 detail/prompt는 제공하지 않는다.
    assert A.agent_detail("triage") is None
    assert A.agent_prompt("vision") is None


# ─────────────────────────────────────────────────────────────────────────────
# 5) 라이브 상태 연결 (허구 상태 금지)
# ─────────────────────────────────────────────────────────────────────────────
def test_status_working_only_when_running():
    agents = A.agent_definitions()
    # 실행 중 + role 일치 → working, 나머지는 idle
    st = {"running": True, "role": "developer", "activity": "bash 실행"}
    out = A.with_live_status([dict(a) for a in agents], st)
    by_id = {a["id"]: a for a in out}
    assert by_id["developer"]["status"] == "working"
    assert by_id["developer"]["activity"] == "bash 실행"
    assert by_id["planner"]["status"] == "idle"
    # 실행 중이 아니면 working이 아니다 — 마지막 role은 recent(최근 실행)로만 표시.
    st2 = {"running": False, "role": "planner", "activity": ""}
    out2 = A.with_live_status([dict(a) for a in agents], st2)
    by_id2 = {a["id"]: a for a in out2}
    assert by_id2["planner"]["status"] == "recent"
    assert by_id2["developer"]["status"] == "idle"
    assert all(a["status"] != "working" for a in out2)
    # status 없음(session 미지정) → 전부 idle.
    out3 = A.with_live_status([dict(a) for a in agents], None)
    assert all(a["status"] == "idle" for a in out3)


# ─────────────────────────────────────────────────────────────────────────────
# 6) 상세 화면 metadata
# ─────────────────────────────────────────────────────────────────────────────
def test_agent_detail_tool_details():
    dev = A.agent_detail("developer")
    assert dev is not None
    names = {t["name"] for t in dev["tool_details"]}
    assert names == set(dev["tools"])
    # mutation 도구는 approval_required=True로 표시된다.
    write = next(t for t in dev["tool_details"] if t["name"] == "write_file")
    assert write["approval_required"] is True
    read = next(t for t in dev["tool_details"] if t["name"] == "read_file")
    assert read["approval_required"] is False
    # reviewer 상세는 실제 스키마(전체 도구)를 공개하되 정책 노트로 검증 전용임을 밝힌다.
    rev = A.agent_detail("reviewer")
    assert rev is not None and "write_file" in rev["tools"]
    assert rev["policy_note"], "reviewer 정책 노트가 비어 있다"


# ─────────────────────────────────────────────────────────────────────────────
# 7) 실제 HTTP API (TestClient — 라이브 서버 없이 라우팅·404·secret 경계 검증)
# ─────────────────────────────────────────────────────────────────────────────
def test_api_agents_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/agents")
    assert r.status_code == 200
    d = r.json()
    assert [a["id"] for a in d["agents"]] == ["developer", "planner", "reviewer", "chat"]
    # 응답 본문에 secret 키/값이 없어야 한다(API 경계).
    blob = str(d)
    assert "api_key" not in blob and "sk-" not in blob
    assert d["active_role"] == ""  # session 미지정 → 실행 role 없음


def test_api_agent_detail_and_prompt():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/agents/developer").status_code == 200
    p = c.get("/api/agents/developer/prompt")
    assert p.status_code == 200
    assert p.json()["prompt"].startswith("# Developer Agent")
    # 없는 role / prompt가 없는 내부 role은 404.
    assert c.get("/api/agents/ghost").status_code == 404
    assert c.get("/api/agents/ghost/prompt").status_code == 404
    assert c.get("/api/agents/vision/prompt").status_code == 404
    assert c.get("/api/agents/triage").status_code == 404


if __name__ == "__main__":
    import sys
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)
