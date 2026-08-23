"""Bounded RSI — promotion gate (사전식 lexicographic 판정).

candidate(config/프롬프트 변경)를 baseline과 고정 benchmark로 비교해 승격 여부를 판정한다.
main을 직접 수정하지 않는다. auto-merge 하지 않는다 — 최종 승인은 사람이 한다.
이 모듈은 R1의 '판정' 부분만 담당한다. candidate worktree 실행/merge는 별도(미구현).

사전식 우선순위(지침 §6):
  1. success_rate가 baseline보다 (min_sr_drop 이상) 나빠지면 → REJECT
  2. 성공률 유지 → cost_per_success 낮으면 PROMOTE, 높으면 REJECT
  3. 비용도 비슷(rel_tol) → elapsed_p50 낮으면 PROMOTE
  4. 전부 비슷 → REJECT(동률은 폐기가 기본 — 바꿀 이유 없음)
"""


def promotion_gate(baseline: dict, candidate: dict, *, min_sr_drop: float = 0.0,
                   cost_rel_tol: float = 0.05, elapsed_rel_tol: float = 0.05) -> dict:
    """baseline/candidate는 bench.aggregate(...)['overall']. 결정과 이유를 돌려준다.

    min_sr_drop: 허용 성공률 후퇴(기본 0 — 후퇴 불허). 노이즈가 크면 소폭 허용 가능하나
    권장은 0. candidate 성공률이 baseline보다 이 값을 초과해 낮으면 즉시 탈락.
    """
    b_sr, c_sr = baseline["success_rate"], candidate["success_rate"]
    if c_sr < b_sr - min_sr_drop:
        return {"decision": "REJECT", "reason": f"성공률 후퇴: {c_sr} < {b_sr} (gate 1)"}

    b_cost, c_cost = baseline.get("cost_per_success"), candidate.get("cost_per_success")
    if b_cost is None or c_cost is None:
        return {"decision": "REJECT", "reason": "비용 미측정 — 판정 불가(가격표 없는 모델?)"}

    # 비용이 의미 있게 낮아지면 승격
    if c_cost < b_cost * (1 - cost_rel_tol):
        return {"decision": "PROMOTE", "reason": f"성공률 유지({c_sr}), 비용 {b_cost:.6f}→{c_cost:.6f} 하락 (gate 2)"}
    # 비용이 의미 있게 높아지면 탈락
    if c_cost > b_cost * (1 + cost_rel_tol):
        return {"decision": "REJECT", "reason": f"비용 상승: {c_cost:.6f} > {b_cost:.6f} (gate 2)"}

    # 비용 비슷 → elapsed 비교
    b_el, c_el = baseline.get("elapsed_p50", 0), candidate.get("elapsed_p50", 0)
    if b_el and c_el < b_el * (1 - elapsed_rel_tol):
        return {"decision": "PROMOTE", "reason": f"성공률·비용 동률, elapsed {b_el}→{c_el} 단축 (gate 3)"}

    return {"decision": "REJECT", "reason": "성공률·비용·elapsed 모두 동률 — 바꿀 이유 없음(기본 폐기)"}


def _self_test():
    base = {"success_rate": 1.0, "cost_per_success": 0.0060, "elapsed_p50": 20.0}
    # 성공률 후퇴 → REJECT
    assert promotion_gate(base, {"success_rate": 0.8, "cost_per_success": 0.001, "elapsed_p50": 5})["decision"] == "REJECT"
    # 성공률 유지 + 비용 하락 → PROMOTE
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0048, "elapsed_p50": 20})["decision"] == "PROMOTE"
    # 성공률 유지 + 비용 상승 → REJECT
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0070, "elapsed_p50": 5})["decision"] == "REJECT"
    # 비용 동률 + elapsed 단축 → PROMOTE
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0060, "elapsed_p50": 15})["decision"] == "PROMOTE"
    # 전부 동률 → REJECT
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0060, "elapsed_p50": 20})["decision"] == "REJECT"
    # 비용 미측정 → REJECT
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": None, "elapsed_p50": 5})["decision"] == "REJECT"
    print("RSI promotion gate self-test 통과 ✓ (사전식 6케이스)")


if __name__ == "__main__":
    _self_test()
