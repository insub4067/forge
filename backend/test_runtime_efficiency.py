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


def test_completion_report():
    # 표준 완료 리포트: 요구사항 요약 + 검증. (섹션5 daily-use)
    # commit/push 줄은 실제 결과를 아는 finish()가 _deploy_line으로 붙인다.
    cr = AgentRuntime._completion_report
    r = cr("completed", "요구사항 2\n✓ 로그인\n✓ 실패메시지", "passed")
    assert r.startswith("완료했습니다.")
    assert "✓ 로그인" in r and "테스트·빌드 통과" in r
    r2 = cr("completed_unverified", "요구사항 1\n! 다크모드 — 검증 방법 없음", "unavailable")
    assert "일부 미검증" in r2 and "! 다크모드" in r2 and "미검증" in r2
    # 리포트는 배포 상태를 추측하지 않는다 — 실제 push 결과를 모르기 때문.
    assert "push" not in r and "push" not in r2
    # gate 0개 완료는 "요구사항은 검증 안 됐다"를 숨기지 않는다(G1, 완전 검증으로 오독 방지).
    r3 = cr("completed", "", "passed")
    assert "요구사항 게이트 없음" in r3
    assert "요구사항 게이트 없음" not in r
    print("OK 표준 완료 리포트(요구사항·검증)")


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
    # 역할 정책: developer/chat/vision + 멀티 모드용 planner/reviewer
    assert set(r._policy.keys()) == {"developer", "chat", "vision", "planner", "reviewer"}, r._policy.keys()
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


if __name__ == "__main__":
    test_compaction_thresholds()
    test_skill_selection()
    test_stable_prefix()
    test_project_shrinks_after_compaction()
    test_merge_memory_facts()
    test_completion_report()
    test_merge_gates_ledger()
    test_over_budget()
    test_drop_orphan_tools()
    test_browser_check_local_only()
    test_developer_escalation()
    test_project_memory_needs_process_evidence()
    test_reviewer_context_is_fresh_and_minimal()
    test_gate_coverage_summarize()
    test_model_tier_reaches_pro()
    print("\n전체 통과")

