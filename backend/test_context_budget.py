"""컨텍스트 예산 개념 분리 검증 — provider capability vs 운영 정책이 올바른 관계이고,
런타임 동작이 분리 전과 동일한지 결정적으로 확인한다(LLM/네트워크 없음).

실행: python -m pytest test_context_budget.py -q
"""
from app.config import settings
from app.runtime import agent as A


def test_concept_separation_relationship():
    # 운영 예산은 provider 하드 한도보다 작아야 한다(예산을 하드 한도로 키우지 않는다).
    assert settings.working_context_budget <= settings.hard_context_limit
    # 하위호환: logical_budget == working_context_budget(동일 개념, 기존 이름 유지).
    assert settings.working_context_budget == settings.logical_budget
    # 임계치 순서: compaction < emergency block < 1.0.
    assert 0 < settings.compaction_threshold < settings.emergency_block_threshold < 1.0
    # provider metadata가 존재한다(값 자체는 조정 가능한 metadata).
    assert settings.hard_context_limit > 0 and settings.max_output_tokens > 0


def test_runtime_thresholds_wired_to_config():
    assert A.CONTEXT_COMPACT_RATIO == settings.compaction_threshold
    assert A.CONTEXT_BLOCK_RATIO == settings.emergency_block_threshold


def test_behavior_unchanged():
    # 분리 전 하드코딩(0.75/0.95)과 동일한 판정을 내는지 — working budget 기준.
    b = settings.working_context_budget
    # 압축: 75% 초과에서 True.
    assert A.AgentRuntime._should_compact(int(b * 0.76), b) is True
    assert A.AgentRuntime._should_compact(int(b * 0.74), b) is False
    # 하드 블록: 95% 초과 + 압축 불가일 때만 True.
    assert A.AgentRuntime._should_block(int(b * 0.96), b, compacted=False) is True
    assert A.AgentRuntime._should_block(int(b * 0.96), b, compacted=True) is False
    assert A.AgentRuntime._should_block(int(b * 0.90), b, compacted=False) is False
