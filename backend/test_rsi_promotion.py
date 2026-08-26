"""RSI 승격 판정 회귀 테스트 (P1-D) — 통계적으로 유의한 판정.

외부 리뷰 P1-D: 기존 promotion_gate는 단일 25태스크 점추정 + min_sr_drop=0으로 노이즈에 취약하고
holdout이 없어 벤치 오버핏을 못 걸렀다. 수정: 표본 요건(repeat) + Wilson 신뢰구간 하한 + holdout.

실행: cd backend && python -m pytest test_rsi_promotion.py -q
"""
from rsi import promotion_gate, wilson_lower, is_holdout, HOLDOUT_CODES


def _agg(succ, n, cost=0.0060, el=20.0):
    return {"runs": n, "successes": succ, "success_rate": round(succ / n, 3) if n else 0.0,
            "cost_per_success": cost, "elapsed_p50": el}


BASE = _agg(50, 50)   # 충분한 표본, 100% 성공, 기준 비용


def test_wilson_lower_bounds():
    """Wilson 하한: 표본이 적으면 같은 성공률이라도 하한이 낮다(노이즈 방지)."""
    assert wilson_lower(50, 50) > wilson_lower(5, 5)   # 100% 성공이라도 n=5는 하한이 낮음
    assert 0.0 <= wilson_lower(0, 10) < 0.4
    assert wilson_lower(0, 0) == 0.0


def test_insufficient_samples_rejected():
    """표본 부족(repeat 없이 단일 실행) → REJECT. 통계적 판정 불가."""
    assert promotion_gate(BASE, _agg(25, 25))["decision"] == "REJECT"      # candidate n=25 < 40
    assert promotion_gate(_agg(25, 25), _agg(50, 50))["decision"] == "REJECT"  # baseline n=25


def test_success_rate_regression_by_wilson_rejected():
    """성공률 후퇴(Wilson 하한 기준) → REJECT."""
    assert promotion_gate(BASE, _agg(40, 50, cost=0.001))["decision"] == "REJECT"


def test_holdout_regression_rejects_even_if_cheaper():
    """holdout 성공률 후퇴 → 비용이 아무리 낮아도 REJECT (벤치 오버핏 방어)."""
    d = promotion_gate(BASE, _agg(50, 50, cost=0.0001),
                       baseline_holdout={"success_rate": 1.0},
                       candidate_holdout={"success_rate": 0.8})
    assert d["decision"] == "REJECT" and "holdout" in d["reason"]


def test_holdout_maintained_allows_promotion():
    """holdout 유지 + 성공률 유지 + 비용 하락 → PROMOTE."""
    d = promotion_gate(BASE, _agg(50, 50, cost=0.0048),
                       baseline_holdout={"success_rate": 1.0},
                       candidate_holdout={"success_rate": 1.0})
    assert d["decision"] == "PROMOTE"


def test_cost_and_elapsed_gates_preserved():
    """비용/elapsed 사전식 판정은 그대로."""
    assert promotion_gate(BASE, _agg(50, 50, cost=0.0048))["decision"] == "PROMOTE"   # 비용↓
    assert promotion_gate(BASE, _agg(50, 50, cost=0.0070))["decision"] == "REJECT"   # 비용↑
    assert promotion_gate(BASE, _agg(50, 50, el=15))["decision"] == "PROMOTE"        # elapsed↓
    assert promotion_gate(BASE, _agg(50, 50))["decision"] == "REJECT"               # 전부 동률


def test_missing_cost_rejected():
    assert promotion_gate(BASE, {"runs": 50, "successes": 50, "success_rate": 1.0,
                                 "cost_per_success": None, "elapsed_p50": 5})["decision"] == "REJECT"


def test_holdout_codes_disjoint_and_nonempty():
    """holdout 코드는 비어있지 않고, is_holdout이 일관된다."""
    assert len(HOLDOUT_CODES) >= 3
    for c in HOLDOUT_CODES:
        assert is_holdout(c)
    assert not is_holdout("A")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PASS — RSI promotion gate (P1-D)")
