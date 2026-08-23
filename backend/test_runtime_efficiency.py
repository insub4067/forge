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


if __name__ == "__main__":
    test_compaction_thresholds()
    test_skill_selection()
    test_stable_prefix()
    test_project_shrinks_after_compaction()
    test_browser_check_local_only()
    test_developer_escalation()
    print("\n전체 통과")
