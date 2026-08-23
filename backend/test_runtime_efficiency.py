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
    # 역할은 developer/vision/chat 3개만
    assert set(r._policy.keys()) == {"developer", "chat", "vision"}, r._policy.keys()
    print("OK developer flash+think / Sr(pro) escalation (8-9)")


if __name__ == "__main__":
    test_compaction_thresholds()
    test_skill_selection()
    test_stable_prefix()
    test_developer_escalation()
    print("\n전체 통과")
