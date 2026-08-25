"""gate가 requirement_id를 보존·왕복하는지(merge_gates 순수 검증).

실행: python -m pytest test_gate_requirement_link.py -q
"""
from app.db.store import merge_gates


def test_merge_preserves_requirement_id_new_and_update():
    # 신규 gate: requirement_id 지정
    out = merge_gates([], [{"title": "로그인", "requirement_id": "R1"}])
    assert out[0]["requirement_id"] == "R1"

    # 갱신: 기존에 R1이 있고 incoming이 requirement_id를 안 주면 유지
    existing = [{"id": 1, "title": "로그인", "status": "working", "requirement_id": "R1",
                 "description": "", "verification_method": "", "expected_result": "",
                 "evidence": "{}", "failure_reason": ""}]
    out = merge_gates(existing, [{"title": "로그인", "status": "working"}])
    assert out[0]["requirement_id"] == "R1"

    # 갱신: incoming이 새 requirement_id를 주면 교체
    out = merge_gates(existing, [{"title": "로그인", "requirement_id": "R2"}])
    assert out[0]["requirement_id"] == "R2"


def test_missing_requirement_id_defaults_empty():
    out = merge_gates([], [{"title": "빌드"}])
    assert out[0]["requirement_id"] == ""
