"""Requirement traceability 지표 검증(순수, LLM/DB 없음).

실행: python -m pytest test_traceability.py -q
"""
from app.runtime.traceability import compute_traceability


def _req(i): return {"id": f"R{i}", "text": f"요구{i}"}
def _gate(rid, status): return {"requirement_id": rid, "status": status}


def test_full_coverage_verified():
    reqs = [_req(1), _req(2)]
    gates = [_gate("R1", "passed"), _gate("R2", "passed")]
    m = compute_traceability(reqs, gates)
    assert m["requirements_total"] == 2
    assert m["requirements_with_gate"] == 2
    assert m["requirements_verified"] == 2
    assert m["requirements_unverified"] == 0
    assert m["gate_semantic_coverage"] == 1.0
    assert m["false_completion_candidate"] is False
    assert m["unverified_ids"] == []


def test_partial_and_unverified_flags_false_completion():
    reqs = [_req(1), _req(2), _req(3)]
    gates = [_gate("R1", "passed"), _gate("R2", "failed")]  # R3는 gate 없음
    m = compute_traceability(reqs, gates)
    assert m["requirements_with_gate"] == 2       # R1, R2
    assert m["requirements_verified"] == 1        # R1만 passed
    assert m["requirements_unverified"] == 2      # R2, R3
    assert m["gate_semantic_coverage"] == round(2 / 3, 3)
    assert m["false_completion_candidate"] is True
    assert set(m["unverified_ids"]) == {"R2", "R3"}


def test_no_requirements():
    m = compute_traceability([], [_gate("R1", "passed")])
    assert m["requirements_total"] == 0
    assert m["gate_semantic_coverage"] == 0.0
    assert m["false_completion_candidate"] is False


def test_gate_without_requirement_id_ignored():
    # requirement_id가 빈 gate(기존 gate)는 특정 요구사항에 연결되지 않는다.
    reqs = [_req(1)]
    gates = [{"requirement_id": "", "status": "passed"}]
    m = compute_traceability(reqs, gates)
    assert m["requirements_with_gate"] == 0 and m["requirements_unverified"] == 1
    assert m["false_completion_candidate"] is True


def test_multiple_gates_per_requirement():
    reqs = [_req(1)]
    gates = [_gate("R1", "failed"), _gate("R1", "passed")]  # 하나라도 passed면 verified
    m = compute_traceability(reqs, gates)
    assert m["requirements_verified"] == 1 and m["false_completion_candidate"] is False
