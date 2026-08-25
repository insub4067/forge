"""Requirement traceability 지표 — Task IR requirement가 Acceptance Gate로 얼마나 검증되는지
결정적으로 계량한다(순수 함수). completion authority가 아니라 관측 지표다.

false_completion(요구사항을 놓친 채 완료)이 이 프로젝트가 가장 위험하게 보는 실패다. 각
requirement가 gate로 연결됐는지, 그 gate가 실제 passed인지를 대조해 미검증 요구사항을 드러낸다.
"""


def compute_traceability(requirements, gates) -> dict:
    """requirements(list[{id,...}])와 gates(list[{requirement_id,status,...}])로 지표 계산.

    반환:
      requirements_total          — 요구사항 수
      requirements_with_gate      — gate가 하나라도 연결된 요구사항 수
      requirements_verified       — passed gate가 있는 요구사항 수
      requirements_unverified     — passed gate가 없는 요구사항 수(미검증)
      gate_semantic_coverage      — with_gate / total (0~1)
      false_completion_candidate  — 미검증 요구사항이 있으면 True(지금 완료 선언 시 false completion 위험)
      unverified_ids              — 미검증 요구사항 id 목록(무엇이 빠졌는지)
    """
    reqs = [r for r in (requirements or []) if isinstance(r, dict) and r.get("id")]
    total = len(reqs)

    # requirement_id → 그 요구사항에 연결된 gate 상태들
    by_req: dict[str, list[str]] = {}
    for g in (gates or []):
        rid = (g.get("requirement_id") or "").strip() if isinstance(g, dict) else ""
        if rid:
            by_req.setdefault(rid, []).append(str(g.get("status", "")))

    with_gate = 0
    verified = 0
    unverified_ids: list[str] = []
    for r in reqs:
        rid = str(r["id"])
        statuses = by_req.get(rid, [])
        if statuses:
            with_gate += 1
        if "passed" in statuses:
            verified += 1
        else:
            unverified_ids.append(rid)

    unverified = total - verified
    coverage = round(with_gate / total, 3) if total else 0.0
    return {
        "requirements_total": total,
        "requirements_with_gate": with_gate,
        "requirements_verified": verified,
        "requirements_unverified": unverified,
        "gate_semantic_coverage": coverage,
        "false_completion_candidate": unverified > 0,
        "unverified_ids": unverified_ids,
    }
