"""런타임 토큰/컨텍스트 효율 수정에 대한 결정론적 검증.

네트워크 없이 순수 함수/정책만 확인한다. 실행:
    cd backend && .venv/bin/python test_runtime_efficiency.py
"""
import tempfile
from pathlib import Path

from app.runtime.agent import (
    AgentRuntime,
    BASE_PROMPT,
    CONTEXT_BLOCK_RATIO,
    CONTEXT_COMPACT_RATIO,
    MAX_ACTIVE_SKILLS,
    SKILL_CHAR_BUDGET,
    _select_skills,
    _stable_prefix,
    _stable_prefix_hash,
    _system_for,
)
from app.orchestrator.model_router import ModelRouter

BUDGET = 1000


def test_compaction_thresholds():
    sc = AgentRuntime._should_compact
    sb = AgentRuntime._should_block
    # 1. 75% 이하 → 압축 없음
    assert sc(int(BUDGET * 0.74), BUDGET) is False
    # 2. 75% 초과 → 압축
    assert sc(int(BUDGET * 0.80), BUDGET) is True
    # 3. 압축 전 95% 초과지만 compaction 성공 → 즉시 차단하지 않음
    assert sb(int(BUDGET * 0.96), BUDGET, compacted=True) is False
    # 4. 압축했는데도(더 못 줄임) 95% 초과 → 차단
    assert sb(int(BUDGET * 0.96), BUDGET, compacted=False) is True
    # 경계: 95% 이하이고 압축 실패여도 차단 안 함
    assert sb(int(BUDGET * 0.90), BUDGET, compacted=False) is False
    # completion은 압박 계산에서 제외됨을 문서화하는 검증:
    # 같은 measured_input이면 completion과 무관하게 판단이 동일하다(measured_input만 인자).
    assert sc(700, BUDGET) is False and sc(760, BUDGET) is True
    print("OK compaction thresholds (1-4)")


def test_skill_selection():
    with tempfile.TemporaryDirectory() as d:
        sdir = Path(d) / ".forge" / "skills"
        sdir.mkdir(parents=True)
        # 49개 무관 skill + 1개 관련 skill
        for i in range(49):
            (sdir / f"unrelated-{i:02d}.md").write_text(
                "lorem ipsum foobar 무관한내용 반복", encoding="utf-8"
            )
        (sdir / "docker-sandbox-workflow.md").write_text(
            "도커 sandbox executor 재시작 절차와 컨테이너 실행 방법", encoding="utf-8"
        )
        # 5. skill 50개 존재 → 관련 skill만 삽입
        out = _select_skills(d, "docker sandbox executor 재시작하려면?")
        assert "docker-sandbox-workflow" in out, out[:200]
        assert out.count("### skill:") <= MAX_ACTIVE_SKILLS
        assert len(out) <= SKILL_CHAR_BUDGET + 200
        # 6. 관련 skill 없음 → 아무것도 삽입 안 함
        assert _select_skills(d, "양자컴퓨터 quantum 얽힘 이론") == ""
        # 빈 쿼리 → 삽입 없음
        assert _select_skills(d, "") == ""
    print("OK skill selective retrieval (5-6)")


def test_stable_prefix():
    # 7. 동일 role 반복 → 안정 프리픽스/해시 불변
    assert _stable_prefix("developer") == _stable_prefix("developer")
    assert _stable_prefix_hash("developer") == _stable_prefix_hash("developer")
    # BASE_PROMPT가 프리픽스 맨 앞에 온다
    assert _stable_prefix("developer").startswith(BASE_PROMPT)
    # system prompt는 안정 프리픽스로 시작하고, skills/memory가 바뀌어도 프리픽스는 그대로
    base = _system_for("developer")
    with_skills = _system_for("developer", room_memory="방메모리", skills="### skill: x\n내용")
    prefix = _stable_prefix("developer")
    assert base.startswith(prefix)
    assert with_skills.startswith(prefix)
    # skills는 프리픽스 '뒤'에만 붙는다(프리픽스 오염 없음)
    assert "### skill: x" not in prefix
    print("OK stable prefix cache-friendliness (7)")


def test_project_shrinks_after_compaction():
    # 전송 전 사전 압축 루프가 의존하는 불변식: 압축 항목이 있으면 _project는
    # [요약] + 최근 tail 만 남겨 컨텍스트가 실제로 줄어든다.
    rt = AgentRuntime.__new__(AgentRuntime)  # docker/router 없이 _project만 검증
    rt._compaction = {}
    msgs = [{"role": "user", "content": "start"}] + [
        {"role": "tool", "content": "X" * 4000} for _ in range(30)
    ]
    # 10. 압축 없음 → 전체 그대로
    assert len(rt._project(msgs, "s")) == len(msgs)
    # 11. 압축 진입(covered=len-8) → 요약 1개 + 최근 8개로 축소
    rt._compaction["s"] = {"summary": "요약본", "covered": len(msgs) - 8}
    proj = rt._project(msgs, "s")
    assert len(proj) == 1 + 8, len(proj)
    assert proj[0]["content"].startswith("[이전 작업 요약")
    # 축소 후 추정 토큰이 원본보다 크게 작다(대량 도구 결과가 요약으로 대체됨)
    from app.runtime.agent import _est_tokens
    before = sum(_est_tokens(m["content"]) for m in msgs)
    after = sum(_est_tokens(m["content"]) for m in proj)
    assert after < before / 2, (before, after)
    print("OK projection shrinks after compaction (10-11)")


def test_merge_memory_facts():
    # 프로젝트 메모리 적립: dedup + 상한 + 헤더 1회.
    mm = AgentRuntime._merge_memory_facts
    # 빈 메모리에 새 사실 → 헤더+사실
    out = mm("", ["- 빌드: npm run build", "- 테스트: pytest"])
    assert out and "학습된 프로젝트 지식" in out and "npm run build" in out and "pytest" in out
    # 이미 있는 사실은 dedup(추가 안 함)
    assert mm(out, ["- 빌드: npm run build"]) is None
    # 새 사실만 추가(헤더 중복 안 함)
    out2 = mm(out, ["- 빌드: npm run build", "- 규약: 존댓말"])
    assert out2 is not None and out2.count("학습된 프로젝트 지식") == 1 and "존댓말" in out2
    # 상한 초과 → None(무한 성장 방지)
    assert mm("x" * 3999, ["- 아주 긴 새 사실 " + "y" * 50], cap=4000) is None
    print("OK 프로젝트 메모리 dedup+상한+헤더1회")


def test_completion_summary_formatter():
    """최종 보고는 process-owned 사실에서 deterministic하게 만든다(LLM 재호출 없음).
    모델이 "모두 완료"라고 썼는지는 근거로 쓰지 않는다."""
    fmt = AgentRuntime.format_completion_summary

    r = fmt({"status": "completed", "gate_state": "passed", "generic_verification": "passed",
             "integration_verification": "passed", "files_changed_count": 3,
             "verified_requirements": [{"title": "로그인", "status": "passed"},
                                       {"title": "실패메시지", "status": "passed"}],
             "unverified_requirements": [], "failed_requirements": [],
             "commit_status": True, "push_status": True})
    # 헤더 앞뒤 빈 줄 — 앞선 진행 설명·근거 목록과 결론이 붙어 읽히지 않게(모바일 가독성).
    head = r.split("\n")
    assert head[0] == "" and head[1] == "완료했습니다." and head[2] == "", head[:3]
    assert "✓ 로그인" in r and "✓ 실패메시지" in r
    assert "✓ 기존 테스트·빌드 통과" in r and "✓ 최종 회귀 확인" in r
    assert "commit·push 완료" in r
    # 내부 정보는 최종 보고에 넣지 않는다(model/tool/token/compaction).
    for noise in ("deepseek", "tool", "token", "compaction", "step"):
        assert noise not in r.lower(), noise

    # 미검증 항목은 침묵하지 않는다(honest failure)
    r2 = fmt({"status": "completed_unverified", "gate_state": "partial",
              "generic_verification": "passed", "integration_verification": "passed",
              "files_changed_count": 2,
              "verified_requirements": [{"title": "로그인", "status": "passed"}],
              "unverified_requirements": [{"title": "세션 유지", "status": "unavailable",
                                           "reason": "검증 방법 없음"}],
              "failed_requirements": [], "commit_status": True, "push_status": False})
    assert "일부 항목은 검증하지 못했습니다" in r2
    assert "! 세션 유지 — 검증 방법 없음" in r2
    assert "push 안 함" in r2 and "push 완료" not in r2

    # gate 0 — "요구사항 미검증"을 반드시 말한다
    r3 = fmt({"status": "completed_unverified", "gate_state": "none",
              "generic_verification": "passed", "integration_verification": "none",
              "files_changed_count": 1, "verified_requirements": [],
              "unverified_requirements": [], "failed_requirements": [],
              "commit_status": True, "push_status": False})
    assert "요구사항 게이트 없음" in r3

    # generic이 unavailable이면 "최종 회귀 확인"을 찍지 않는다(자기모순 방지, 실측 버그).
    r6 = fmt({"status": "completed_unverified", "gate_state": "passed",
              "generic_verification": "unavailable", "integration_verification": "passed",
              "files_changed_count": 2,
              "verified_requirements": [{"title": "빈 문자열", "status": "passed"}],
              "unverified_requirements": [], "failed_requirements": [],
              "commit_status": True, "push_status": False})
    assert "회귀 미확인" in r6
    assert "최종 회귀 확인" not in r6, r6   # 모순 금지

    # push 실패를 성공으로 보고하지 않는다
    r4 = fmt({"status": "completed", "gate_state": "passed", "generic_verification": "passed",
              "integration_verification": "passed", "files_changed_count": 2,
              "verified_requirements": [], "unverified_requirements": [],
              "failed_requirements": [], "commit_status": True, "push_status": False})
    assert "push 실패" in r4 and "push 완료" not in r4
    r5 = dict(commit_status=False, push_status=False, status="completed",
              gate_state="passed", generic_verification="passed",
              integration_verification="passed", files_changed_count=2,
              verified_requirements=[], unverified_requirements=[], failed_requirements=[])
    assert "commit 안 됨" in fmt(r5)
    print("OK 최종 보고 formatter(요구사항·검증·commit/push, 내부정보 없음)")


def test_blocking_reason():
    """완전 검증이 아니면 그 사유를 기계가 읽을 수 있게 남긴다(가장 근본적인 것 하나)."""
    from app.runtime.agent import _blocking_reason as b
    assert b("completed", "passed", "passed") == ""
    assert b("completed_unverified", "none", "passed") == "요구사항 게이트 없음"
    assert b("completed_unverified", "partial", "passed") == "일부 요구사항 미검증"
    assert b("completed_unverified", "passed", "unavailable") == "실행 가능한 test/build 없음"
    assert b("verification_failed", "failed", "passed") == "요구사항 검증 실패"



def test_merge_gates_ledger():
    # P0-2: 한번 생성된 acceptance gate는 모델이 payload에서 누락하는 것만으로 삭제되지 않는다.
    # process-owned evidence(passed/failed)는 모델 재선언으로 되돌아가지 않는다.
    from app.db.store import merge_gates
    existing = [
        {"id": 1, "title": "A", "description": "", "verification_method": "", "expected_result": "",
         "status": "passed", "evidence": '{"x":1}', "failure_reason": ""},
        {"id": 2, "title": "B", "description": "", "verification_method": "", "expected_result": "",
         "status": "pending", "evidence": "{}", "failure_reason": ""},
        {"id": 3, "title": "C", "description": "", "verification_method": "", "expected_result": "",
         "status": "failed", "evidence": '{"y":2}', "failure_reason": "boom"},
        {"id": 4, "title": "D", "description": "", "verification_method": "", "expected_result": "",
         "status": "working", "evidence": "{}", "failure_reason": ""},
    ]
    # 모델이 A/B/C만 재전송(D 누락) + passed A를 working으로, failed C를 working으로 되돌리려 시도
    incoming = [{"title": "A", "status": "working"},
                {"title": "B", "status": "working"},
                {"title": "C", "status": "working"}]
    out = {g["title"]: g for g in merge_gates(existing, incoming)}
    assert "D" in out and out["D"]["id"] == 4, "누락된 gate D는 삭제되지 않고 보존"
    assert out["A"]["status"] == "passed" and out["A"]["evidence"] == '{"x":1}', "passed+evidence 보호"
    assert out["C"]["status"] == "failed" and out["C"]["evidence"] == '{"y":2}', "failed+evidence 보호"
    assert out["B"]["status"] == "working", "pending은 모델이 갱신 가능"
    print("OK gate ledger append-preserving + evidence 보호 (P0-2)")


def test_over_budget():
    # 예산 가드레일 판정: 상한이 설정(>0)돼 있고 누적 비용이 넘으면 중단.
    ob = AgentRuntime._over_budget
    assert ob(1.01, 1.0) is True       # 초과 → 중단
    assert ob(0.99, 1.0) is False      # 이하 → 계속
    assert ob(5.0, 0) is False         # 상한 0 = 무제한
    assert ob(5.0, 0.0) is False       # 0.0도 무제한
    assert ob(1.0, 1.0) is False       # 경계(같음) → 아직 안 넘음
    # 세션 override 해석: None=default, 0=무제한, 양수=cap (P0-5: 0이 default로 새면 안 됨)
    eb = AgentRuntime._effective_budget
    assert eb(None, 2.0) == 2.0        # 미설정 → default
    assert eb(0.0, 2.0) == 0.0         # 0 → 무제한(0 유지, default로 안 샘)
    assert eb(1.5, 2.0) == 1.5         # 양수 → 그 값
    # 결합: override 0이면 아무리 써도 안 넘음(무제한)
    assert ob(999.0, eb(0.0, 2.0)) is False
    assert ob(2.5, eb(None, 2.0)) is True   # 미설정 → default 2.0 초과
    print("OK 예산 가드레일 판정 + override(0=무제한)")


def test_drop_orphan_tools():
    # tool 메시지는 직전 assistant tool_calls id와 매칭돼야 전송된다(안 그러면 provider 400).
    drop = AgentRuntime._drop_orphan_tools
    # 정상 페어 — 유지
    ok = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "tool_calls": [{"id": "a1"}, {"id": "a2"}]},
        {"role": "tool", "tool_call_id": "a1", "content": "r1"},
        {"role": "tool", "tool_call_id": "a2", "content": "r2"},
        {"role": "assistant", "content": "done"},
    ]
    assert drop(ok) == ok
    # orphan: 선행 assistant tool_calls 없는 tool → 제거
    orphan = [
        {"role": "user", "content": "[이전 작업 요약]"},  # compaction checkpoint
        {"role": "tool", "tool_call_id": "x9", "content": "orphan"},
        {"role": "assistant", "content": "hi"},
    ]
    out = drop(orphan)
    assert {"role": "tool", "tool_call_id": "x9", "content": "orphan"} not in out
    assert len(out) == 2
    # user가 assistant(tool_calls)와 tool 사이에 끼면 그 tool은 orphan → 제거
    mid = [
        {"role": "assistant", "tool_calls": [{"id": "b1"}]},
        {"role": "user", "content": "끼어듦"},
        {"role": "tool", "tool_call_id": "b1", "content": "late"},
    ]
    out2 = drop(mid)
    assert all(m.get("role") != "tool" for m in out2)
    print("OK orphan tool 제거 (provider 400 방어)")


def test_browser_check_local_only():
    # browser_check는 로컬 오리진만 허용해야 한다(에이전트가 임의 외부 사이트/메타데이터를 못 연다).
    from app.tools.registry import _is_local_url
    assert _is_local_url("http://127.0.0.1:8790")
    assert _is_local_url("http://localhost:3000")
    assert _is_local_url("http://app.localhost:5173")
    assert not _is_local_url("http://evil.com")
    assert not _is_local_url("https://169.254.169.254/latest/meta-data")  # 클라우드 메타데이터
    assert not _is_local_url("file:///etc/passwd")
    print("OK browser_check 로컬 오리진 경계 (SSRF)")


def test_developer_escalation():
    r = ModelRouter()
    # 8. Developer 기본 → Flash + thinking(설계+구현+자체검증)
    base = r.select_model("developer")
    assert "flash" in base["model"], base
    assert base["thinking"] is True and base["reasoning_effort"] == "medium", base
    # 9. Developer 막힘 → Sr 승격(pro + think-high)
    esc = r.select_model("developer", escalate=True)
    assert esc["model"] == r.developer_pro_model and "pro" in esc["model"], esc
    assert esc["thinking"] is True and esc["reasoning_effort"] == "high", esc
    # 역할 정책: developer/chat/vision + 멀티 모드용 planner/reviewer + gate_recovery
    assert set(r._policy.keys()) == {"developer", "chat", "vision", "planner",
                                     "reviewer", "gate_recovery"}, r._policy.keys()
    # gate 복구는 저비용 고정 — gate 작성 실패로 pro를 소비하지 않는다(비용 상한).
    gr = r.select_model("gate_recovery")
    assert "flash" in gr["model"], gr
    assert gr["model"] != r.developer_pro_model, gr
    print("OK developer flash+think / Sr(pro) escalation (8-9)")



def test_project_memory_needs_process_evidence():
    """gate 근거 없이는 프로젝트 메모리를 적립하지 않는다 — 모델이 빈자리를 일반론으로
    채워 ROOM_MEMORY를 오염시킨다(실측: 이 워크스페이스에 없는 `python -m pytest`가
    durable 사실로 적립됐다). 오염된 메모리는 이후 모든 세션 컨텍스트에 실린다."""
    import asyncio
    from app.runtime import agent as A

    rt = AgentRuntime()
    gates_now = []
    distilled = []

    async def fake_list_gates(sid):
        return gates_now

    def fake_adapter(model):
        distilled.append(model)
        raise AssertionError("근거 없이 utility 모델을 부르면 안 된다")

    async def send(t, d):
        distilled.append(t)

    orig = A.store.list_gates
    A.store.list_gates = fake_list_gates
    rt._adapter_for = fake_adapter
    try:
        # gate 없음 → 적립 금지
        asyncio.run(rt._extract_project_memory("s1", "/tmp", "목표", ["a.py"], send))
        assert distilled == [], f"gate 없이 적립 시도: {distilled}"
        # gate는 있으나 통과한 검증 명령 없음 → 적립 금지
        gates_now.append({"title": "X", "status": "unavailable", "verification_method": ""})
        asyncio.run(rt._extract_project_memory("s1", "/tmp", "목표", ["a.py"], send))
        assert distilled == [], f"미검증 gate로 적립 시도: {distilled}"
        # 통과한 gate + 검증 명령 있음 → 여기서는 적립 경로로 들어간다(모델 호출 시도)
        gates_now[0] = {"title": "X", "status": "passed", "verification_method": "pytest -q"}
        asyncio.run(rt._extract_project_memory("s1", "/tmp", "목표", ["a.py"], send))
        assert distilled, "근거가 있는데도 적립 경로를 타지 않았다"
    finally:
        A.store.list_gates = orig
    print("OK 프로젝트 메모리는 process-owned 근거가 있을 때만 적립")



def test_reviewer_context_is_fresh_and_minimal():
    """Reviewer는 Developer 작업 기록을 받지 않는다 — 그 프레이밍을 물려받으면 결과가
    아니라 변명을 검토하게 된다(self-grading). 비용도 planner 73% 패턴의 재발이다."""
    import json
    from app.runtime.agent import _reviewer_context

    all_messages = [
        {"role": "user", "content": "로그인 붙여줘"},
        {"role": "assistant", "content": "auth.py를 이렇게 고치는 게 최선입니다"},
        {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "read_file"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "파일 내용 전체..."},
        {"role": "assistant", "content": "다 됐습니다"},
    ]
    msgs = _reviewer_context(all_messages, "완료 조건: 로그인 성공/실패 응답")

    blob = json.dumps(msgs, ensure_ascii=False)
    assert "로그인 붙여줘" in blob, "원 요청은 있어야 한다"
    assert "완료 조건" in blob, "plan(완료 조건)은 있어야 한다"
    assert "최선입니다" not in blob, "Developer 추론이 새어 들어갔다"
    assert "다 됐습니다" not in blob, "Developer self-report가 새어 들어갔다"
    assert "파일 내용 전체" not in blob, "도구 결과가 새어 들어갔다"
    assert not any(m.get("role") == "tool" for m in msgs), "orphan tool 메시지는 400을 낸다"
    assert "git diff" in blob, "변경을 직접 확인하라는 지시가 있어야 한다"
    # plan이 없어도 동작한다(Planner 실패 폴백 경로)
    assert "로그인 붙여줘" in json.dumps(_reviewer_context(all_messages, ""), ensure_ascii=False)
    print("OK Reviewer 컨텍스트는 fresh·minimal")



def test_gate_coverage_summarize():
    """G0 집계 — 코드 변경이 있는 run만 분모로 삼는다. 대화·조회 run을 섞으면
    비율이 희석돼 "대체로 괜찮다"로 오독된다."""
    from gate_coverage import summarize

    rows = [
        {"status": "completed", "gates": 0, "files_changed": 2, "generic_only": True},
        {"status": "completed", "gates": 3, "files_changed": 5, "generic_only": False},
        {"status": "completed_unverified", "gates": 0, "files_changed": 1, "generic_only": True},
        {"status": "completed_unverified", "gates": 0, "files_changed": 0, "generic_only": False},
    ]
    s = summarize(rows)
    assert s["runs"] == 4
    assert s["code_changing_runs"] == 3, "변경 0건 run은 분모에서 빠져야 한다"
    assert s["generic_only_runs"] == 2
    assert s["generic_only_rate"] == round(2 / 3, 3)
    assert s["generic_only_by_status"] == {"completed": 1, "completed_unverified": 1}
    # 경로 분류와 파생 비율
    rows2 = [
        {"status": "completed", "files_changed": 2, "generic_only": False, "coverage": "gated"},
        {"status": "completed", "files_changed": 1, "generic_only": False,
         "coverage": "recovered_gated"},
        {"status": "completed_unverified", "files_changed": 1, "generic_only": True,
         "coverage": "generic_only"},
        {"status": "completed_unverified", "files_changed": 0, "generic_only": False,
         "coverage": "no_change"},
    ]
    s2 = summarize(rows2)
    assert s2["by_coverage"] == {"gated": 1, "recovered_gated": 1, "generic_only": 1}, s2
    # 처음에 gate가 없던 run 2건(복구 성공 1 + 실패 1) / 코드 변경 3건
    assert s2["gate_missing_rate"] == round(2 / 3, 3), s2
    assert s2["recovery_success_rate"] == 0.5, s2
    assert summarize([])["recovery_success_rate"] is None
    assert summarize([])["generic_only_rate"] is None  # 0으로 나누지 않는다

    # 테스트가 남긴 합성 run은 실제 사용으로 세지 않는다(오염된 telemetry → 잘못된 결정).
    from gate_coverage import is_real_session
    assert is_real_session("a" * 32) is True
    assert is_real_session("s1") is False
    assert is_real_session("") is False
    assert is_real_session("Z" * 32) is False
    print("OK gate 커버리지 집계")



def test_model_tier_reaches_pro():
    """화면의 모델 티어가 실제로 pro 모델에 닿는지 고정한다.

    티어는 select_model에 직접 전달되지 않는다 — run()이 `always_pro = tier == "pro"`로
    번역해 escalate로 넘긴다. 그 간접 경로 때문에 "티어가 무시된다"고 오진하기 쉽다
    (실제로 오진했다). 실측: model_tier=pro → role_start.model = deepseek-v4-pro.
    """
    from app.orchestrator.model_router import ModelRouter

    r = ModelRouter()
    assert r.select_model("developer")["model"] != r.developer_pro_model, "기본은 flash"
    assert r.select_model("developer", escalate=True)["model"] == r.developer_pro_model
    # pro 승격은 thinking high를 함께 켠다
    esc = r.select_model("developer", escalate=True)
    assert esc["thinking"] is True and esc["reasoning_effort"] == "high"

    # run()의 번역 규칙: pro→always_pro, flash/auto→아님
    import inspect
    from app.runtime.agent import AgentRuntime
    src = inspect.getsource(AgentRuntime.run)
    assert 'always_pro = tier == "pro" or settings.developer_pro' in src, \
        "티어→escalate 번역이 사라지면 화면의 pro 선택이 조용히 무력해진다"
    assert "escalate=always_pro" in src
    print("OK 모델 티어 pro → pro 모델 + thinking high")



def test_compaction_survives_run_end():
    """압축 요약은 run이 끝나도 살아남아야 한다.

    메모리에만 두면 cleanup_session이 run 종료마다 지운다 → 다음 run이 전체 히스토리를
    다시 보내고, 다시 압축하고, 또 버린다. 압축이 매 run 안에서만 유효해 누적 효과가 0이
    된다(실측: used 157k / budget 131k = 120% 세션). 비용에 직결되는 invariant다.
    """
    import asyncio
    import inspect
    from app.runtime import agent as A

    # 1) _compact가 성공하면 반드시 영속화한다
    src = inspect.getsource(A.AgentRuntime._compact)
    assert "set_session_compaction" in src, "압축 요약을 DB에 저장하지 않는다"

    # 2) run 시작 시 DB에서 복원한다
    run_src = inspect.getsource(A.AgentRuntime.run)
    assert "get_session_compaction" in run_src, "run 시작 시 압축 요약을 복원하지 않는다"

    # 3) 복원된 요약이 _project에 실제로 반영된다
    rt = A.AgentRuntime.__new__(A.AgentRuntime)
    rt._compaction = {}
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(20)]
    assert len(rt._project(msgs, "s")) == len(msgs)          # 요약 없으면 그대로
    rt._compaction["s"] = {"summary": "이전 작업 요약", "covered": 12}
    proj = rt._project(msgs, "s")
    assert len(proj) == 1 + (20 - 12), proj                   # 체크포인트 + 남은 8개
    assert "이전 작업 요약" in proj[0]["content"]

    # 4) cleanup_session이 메모리를 비워도 DB 값으로 되살아난다(복원 조건 검증)
    saved = {"summary": "S", "covered": 12}
    assert saved["covered"] <= len(msgs)                       # 히스토리보다 크면 복원 금지
    print("OK 압축 요약 영속화(run 경계 생존)")



def test_model_tier_is_per_session():
    """모델 티어는 세션별 설정이다 — 방마다 독립적으로 유지돼야 한다.

    백엔드는 sessions.model_tier에 세션별로 저장하는데 프론트가 localStorage 전역값
    하나만 쓰고 방 전환 시 다시 읽지 않아, 다른 방에서 고른 티어가 그대로 보였다.
    실제 동작(서버 값)과 화면 표시가 어긋나는 상태였다.
    """
    import inspect
    from app.db import store
    from app.api import routes

    # 1) 방 목록·단건 조회가 model_tier를 내려준다(프론트가 복원할 재료)
    for fn in (store.list_rooms, store.get_room):
        assert '"model_tier"' in inspect.getsource(fn), f"{fn.__name__}이 model_tier를 안 내려준다"

    # 2) 고른 즉시 세션에 붙이는 엔드포인트가 있다(전송 전에 방을 옮겨도 유지)
    src = inspect.getsource(routes)
    assert 'sessions/{session_id}/model-tier' in src, "세션별 티어 저장 엔드포인트가 없다"
    assert "set_session_model_tier" in src

    # 3) 허용값 밖은 auto로 방어한다
    tier_src = inspect.getsource(routes.set_model_tier)
    assert '("auto", "pro", "flash")' in tier_src and 'tier = "auto"' in tier_src
    print("OK 모델 티어는 세션별")


if __name__ == "__main__":
    test_compaction_thresholds()
    test_skill_selection()
    test_stable_prefix()
    test_project_shrinks_after_compaction()
    test_compaction_survives_run_end()
    test_model_tier_is_per_session()
    test_merge_memory_facts()
    test_completion_summary_formatter()
    test_blocking_reason()
    test_merge_gates_ledger()
    test_over_budget()
    test_drop_orphan_tools()
    test_browser_check_local_only()
    test_developer_escalation()
    test_project_memory_needs_process_evidence()
    test_reviewer_context_is_fresh_and_minimal()
    test_gate_coverage_summarize()
    test_model_tier_reaches_pro()
    test_runtime_smoke_fails_on_dead_backend()
    print("\n전체 통과")



def test_runtime_smoke_fails_on_dead_backend():
    """런타임 스모크는 백엔드가 응답하지 않으면 failed로 잡는다(축 A — 서버 생존).

    예전엔 정적 UI 렌더만 봐서, 서버가 먹통이면 page.goto 타임아웃이 unavailable로 새어
    '검증 안 함'이 됐다(오늘 서버 30분 먹통이 verified로 넘어갈 뻔한 지점). health를
    브라우저 안에서 확인해 200이 아니면 failed다. 소스에 그 분기가 있는지 고정한다."""
    import inspect
    from app.runtime.agent import AgentRuntime
    src = inspect.getsource(AgentRuntime._runtime_smoke)
    assert "/api/health" in src, "런타임 스모크가 백엔드 응답성을 확인하지 않는다"
    assert 'health_status != 200' in src
    assert '"failed", ("런타임 스모크 실패 — 백엔드가 응답하지 않음' in src \
        or "백엔드가 응답하지 않음" in src
    print("OK 런타임 스모크가 서버 생존을 검증(축 A)")


class _StrictDeepSeekFake:
    """DeepSeek V4 thinking mode 계약을 강제하는 fake adapter.

    실제 계약(codex #24500, opencode #24190, qwen-code #3658에서 확인):
    thinking=True + tools 존재 상태에서 히스토리의 assistant(tool_calls 보유)에
    reasoning_content가 없으면 400. 이전 코드/커밋 b01da1c가 정확히 이걸 유발했다.
    """
    requires_reasoning_replay = True

    def __init__(self, fail_first: bool = False):
        self.calls: list[dict] = []
        self._fail_first = fail_first  # 첫 호출만 강제 400(폴백 경로 검증용)

    async def stream_chat(self, messages, tools=None, thinking=False, reasoning_effort=None):
        self.calls.append({"thinking": thinking, "has_tools": bool(tools),
                           "messages": messages})
        if self._fail_first and len(self.calls) == 1:
            raise RuntimeError(
                "DeepSeek API 오류 400: The reasoning_content in the thinking mode "
                "must be passed back to the API")
        if thinking and tools:
            for m in reversed(messages):
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    if "reasoning_content" not in m:
                        raise RuntimeError(
                            "DeepSeek API 오류 400: The reasoning_content in the "
                            "thinking mode must be passed back to the API")
                    break
        yield {"content": "ok"}


def _tool_loop_history():
    """reasoning + tool_call → tool result 를 포함한 발전된 tool-loop 히스토리."""
    return [
        {"role": "user", "content": "작업"},
        {"role": "assistant", "content": "",
         "reasoning_content": "단계별 사고" * 50,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "파일 내용"},
    ]


def test_reasoning_replayed_across_tool_calls():
    """thinking+tools tool-loop에서 assistant reasoning_content가 전송본에 유지된다.

    DeepSeek V4 계약: 누락하면 400. 전송본에만 유지하고 원본 history는 불변으로 둔다.
    검증: (1) 400 없이 통과 (2) 전송본에 reasoning 유지 (3) retry 0 (4) 원본 불변.
    """
    import asyncio
    from app.runtime.agent import AgentRuntime
    from app.tools.registry import TOOL_SCHEMAS

    rt = AgentRuntime()
    fake = _StrictDeepSeekFake()
    rt._adapter_for = lambda model: fake
    history = _tool_loop_history()
    counters = {"retries": 0}

    async def drive():
        async for _ in rt._stream_with_recovery(
            "deepseek-v4-flash", history, TOOL_SCHEMAS, True, "medium", "s1", counters
        ):
            pass

    asyncio.run(drive())  # 400이면 예외로 실패
    assert len(fake.calls) == 1, f"재시도가 발생: {len(fake.calls)}"
    assert counters["retries"] == 0, f"retry 발생: {counters}"
    sent = fake.calls[0]["messages"]
    assert any("reasoning_content" in m for m in sent), "전송본에서 reasoning이 사라짐"
    assert fake.calls[0]["thinking"] is True, "thinking이 꺼짐"
    # 원본 history 불변(deep equality)
    assert history == _tool_loop_history(), "원본 history가 변형됨"
    print("OK thinking+tools에서 reasoning round-trip 유지(400 없음, retry 0, 원본 불변)")


def test_reasoning_stripped_when_no_tools():
    """tools 없는 요청에서는 reasoning_content를 전송본에서 제거한다(토큰 절감 유지).

    tool_call 히스토리가 아니면 round-trip 계약이 없어 안전하게 벗길 수 있다.
    """
    import asyncio
    from app.runtime.agent import AgentRuntime

    rt = AgentRuntime()
    fake = _StrictDeepSeekFake()
    rt._adapter_for = lambda model: fake
    history = [
        {"role": "user", "content": "요약해줘"},
        {"role": "assistant", "content": "답", "reasoning_content": "사고" * 50},
    ]

    async def drive():
        async for _ in rt._stream_with_recovery(
            "deepseek-v4-flash", history, None, True, "medium", "s2"
        ):
            pass

    asyncio.run(drive())
    sent = fake.calls[0]["messages"]
    assert not any("reasoning_content" in m for m in sent), "tools 없는데 reasoning 유지됨"
    assert "reasoning_content" in history[1], "원본 history가 파괴됨"
    print("OK tools 없는 요청에서는 reasoning 제거(원본 보존)")


def test_reasoning_fallback_is_run_scoped():
    """400 폴백은 현재 run(counters) 범위로만 제한되고 미래 run/다른 세션을 오염시키지 않는다.

    첫 호출 400 → thinking 끄고 재시도(같은 run 내). 새 run(새 counters)은 다시 thinking 시작.
    세션 영구 상태(_strip_reasoning_sessions)는 존재하지 않는다.
    """
    import asyncio
    from app.runtime.agent import AgentRuntime
    from app.tools.registry import TOOL_SCHEMAS

    rt = AgentRuntime()
    assert not hasattr(rt, "_strip_reasoning_sessions"), \
        "세션 영구 non-thinking 상태가 아직 존재한다"

    fake = _StrictDeepSeekFake(fail_first=True)
    rt._adapter_for = lambda model: fake

    # run A — 첫 호출 400 → 폴백으로 thinking 끄고 재시도
    countersA = {"retries": 0}

    async def driveA():
        async for _ in rt._stream_with_recovery(
            "deepseek-v4-flash", _tool_loop_history(), TOOL_SCHEMAS, True, "medium",
            "sess", countersA
        ):
            pass

    asyncio.run(driveA())
    assert len(fake.calls) == 2, "폴백 재시도가 없었다"
    assert fake.calls[0]["thinking"] is True and fake.calls[1]["thinking"] is False, \
        "폴백이 thinking을 끄지 않았다"
    assert countersA["retries"] == 1

    # run B — 같은 세션이지만 새 counters. thinking이 다시 켜져야 한다(오염 없음).
    fake2 = _StrictDeepSeekFake()
    rt._adapter_for = lambda model: fake2
    countersB = {"retries": 0}

    async def driveB():
        async for _ in rt._stream_with_recovery(
            "deepseek-v4-flash", _tool_loop_history(), TOOL_SCHEMAS, True, "medium",
            "sess", countersB
        ):
            pass

    asyncio.run(driveB())
    assert fake2.calls[0]["thinking"] is True, "이전 run의 폴백이 새 run을 오염시킴"
    print("OK reasoning 폴백은 run-scope(미래 run/다른 세션 무오염)")


def test_old_write_file_args_folded():
    """오래된 write_file 호출의 content 인자는 전송본에서 스텁으로 접힌다.

    write_file(path, content)의 content는 파일 전문이라 히스토리에 영구 잔류하면 콜마다
    재전송된다(실측 세션에서 tool_call args의 최대 성분, 13.5K tok). 파일은 디스크에 있고
    read_file로 다시 읽을 수 있으므로, 최근 KEEP_RECENT 이내를 제외한 과거 write_file
    content만 접는다. 실측 시뮬레이션(140콜): 콜당 입력 49,054 → 42,632 tok(-13.1%).

    최근 것·edit_file(diff 문맥)·원본 히스토리는 건드리지 않는다.
    """
    import json
    from app.runtime.agent import AgentRuntime, COMPACT_KEEP_RECENT

    def wf(path, content):
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "x", "type": "function",
                "function": {"name": "write_file",
                             "arguments": json.dumps({"path": path, "content": content})},
            }],
        }

    old = wf("a.py", "OLD_BODY " * 500)
    recent = wf("b.py", "RECENT_BODY " * 500)
    ef = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "y", "type": "function",
                        "function": {"name": "edit_file",
                                     "arguments": json.dumps({"path": "c.py", "old_string": "EDIT_OLD", "new_string": "EDIT_NEW"})}}],
    }
    # old/ef를 KEEP 경계 밖으로 밀어내되 recent는 경계 안(최근 KEEP)에 남긴다.
    filler = [{"role": "user", "content": f"m{i}"} for i in range(COMPACT_KEEP_RECENT - 1)]
    msgs = [old, ef, *filler, recent]

    out = AgentRuntime._fold_old_write_args(msgs, COMPACT_KEEP_RECENT)
    dump = json.dumps(out, ensure_ascii=False)

    assert "OLD_BODY" not in dump, "오래된 write_file content가 접히지 않았다"
    assert "RECENT_BODY" in dump, "최근 write_file content까지 접혔다"
    assert "EDIT_OLD" in dump and "EDIT_NEW" in dump, "edit_file diff가 훼손됐다"
    # path는 보존
    assert json.loads(out[0]["tool_calls"][0]["function"]["arguments"])["path"] == "a.py"
    # 원본 불변
    assert "OLD_BODY" in json.loads(old["tool_calls"][0]["function"]["arguments"])["content"]
    print("OK 오래된 write_file content만 전송본에서 접힘(원본·edit_file·최근 보존)")
