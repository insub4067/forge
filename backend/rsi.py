"""Bounded RSI — promotion gate (사전식 lexicographic 판정).

candidate(config/프롬프트 변경)를 baseline과 고정 benchmark로 비교해 승격 여부를 판정한다.
main을 직접 수정하지 않는다. auto-merge 하지 않는다 — 최종 승인은 사람이 한다.

외부 리뷰 P1-D 반영 — 통계적으로 유의한 판정:
  0. 표본 요건: repeat 집계로 최소 표본 이상이어야 판정한다(단일 25태스크 = 노이즈).
  1. Holdout: RSI 판정에 절대 쓰지 않는 holdout 태스크(HOLDOUT_CODES) 성공률이 후퇴하면
     비용이 아무리 낮아도 즉시 REJECT — 벤치(promotion set) 오버핏을 걸러낸다.
  2. 성공률: 점추정이 아니라 **Wilson 신뢰구간 하한**으로 비교한다. 표본이 적으면 하한이 낮아져
     '우연히 유지된' 후보가 통과하지 못한다.
  3. 비용: 성공률(하한) 유지 → cost_per_success가 의미 있게 낮으면 PROMOTE, 높으면 REJECT.
  4. elapsed: 비용도 비슷 → elapsed_p50 낮으면 PROMOTE.
  5. 전부 비슷 → REJECT(동률은 폐기가 기본 — 바꿀 이유 없음).

baseline/candidate는 bench.aggregate(...)['overall'] (runs·successes·success_rate·cost_per_success·
elapsed_p50 포함). holdout 인자는 holdout 서브셋만 aggregate한 동일 구조(성공률만 있으면 됨).
"""
import math

# RSI 승격 판정에 **절대 쓰지 않는** holdout 태스크. promotion set과 다른 도메인을 대표하도록
# 다양하게 고른다: 탐색후수정·YAGNI·COMPLEX 파이프라인·디버깅·통합. 신규 태스크는 여기에 추가한다.
HOLDOUT_CODES = frozenset({"E", "K", "Q", "U", "X"})


def is_holdout(code: str) -> bool:
    return code in HOLDOUT_CODES


def wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """이항 성공률의 Wilson 신뢰구간 하한 — 표본이 적으면 하한이 낮아진다(노이즈 승격 방지)."""
    if n <= 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - margin) / denom)


def promotion_gate(baseline: dict, candidate: dict, *, min_samples: int = 40,
                   cost_rel_tol: float = 0.05, elapsed_rel_tol: float = 0.05,
                   baseline_holdout: dict | None = None,
                   candidate_holdout: dict | None = None) -> dict:
    """결정과 이유를 돌려준다. baseline/candidate는 bench aggregate의 'overall'."""
    # 0. 표본 요건 — repeat 집계 없이는 판정하지 않는다(단일 실행은 노이즈).
    b_n, c_n = baseline.get("runs", 0), candidate.get("runs", 0)
    if b_n < min_samples or c_n < min_samples:
        return {"decision": "REJECT",
                "reason": f"표본 부족(baseline {b_n}, candidate {c_n} < {min_samples}) — repeat 집계 필요 (gate 0)"}

    # 1. Holdout 후퇴 → 즉시 REJECT (비용 무관). 벤치 특화/오버핏 방어.
    if baseline_holdout is not None and candidate_holdout is not None:
        bh = baseline_holdout.get("success_rate", 0.0)
        ch = candidate_holdout.get("success_rate", 0.0)
        if ch < bh:
            return {"decision": "REJECT",
                    "reason": f"holdout 성공률 후퇴: {ch} < {bh} — 벤치 오버핏 의심 (gate 1: holdout)"}

    # 2. 성공률 — Wilson 하한으로 비교(점추정 아님).
    b_lo = wilson_lower(baseline.get("successes", 0), b_n)
    c_lo = wilson_lower(candidate.get("successes", 0), c_n)
    if c_lo < b_lo:
        return {"decision": "REJECT",
                "reason": f"성공률 Wilson 하한 후퇴: {c_lo:.3f} < {b_lo:.3f} (gate 2)"}

    b_cost, c_cost = baseline.get("cost_per_success"), candidate.get("cost_per_success")
    if b_cost is None or c_cost is None:
        return {"decision": "REJECT", "reason": "비용 미측정 — 판정 불가(가격표 없는 모델?)"}

    # 3. 비용
    if c_cost < b_cost * (1 - cost_rel_tol):
        return {"decision": "PROMOTE",
                "reason": f"성공률 하한 유지({c_lo:.3f}≥{b_lo:.3f}), 비용 {b_cost:.6f}→{c_cost:.6f} 하락 (gate 3)"}
    if c_cost > b_cost * (1 + cost_rel_tol):
        return {"decision": "REJECT", "reason": f"비용 상승: {c_cost:.6f} > {b_cost:.6f} (gate 3)"}

    # 4. elapsed
    b_el, c_el = baseline.get("elapsed_p50", 0), candidate.get("elapsed_p50", 0)
    if b_el and c_el < b_el * (1 - elapsed_rel_tol):
        return {"decision": "PROMOTE", "reason": f"성공률·비용 동률, elapsed {b_el}→{c_el} 단축 (gate 4)"}

    return {"decision": "REJECT", "reason": "성공률·비용·elapsed 모두 동률 — 바꿀 이유 없음(기본 폐기)"}


def _self_test():
    # 충분한 표본(50 runs) 기준선.
    base = {"runs": 50, "successes": 50, "success_rate": 1.0,
            "cost_per_success": 0.0060, "elapsed_p50": 20.0}

    def cand(succ, n=50, cost=0.0060, el=20.0):
        return {"runs": n, "successes": succ, "success_rate": round(succ / n, 3),
                "cost_per_success": cost, "elapsed_p50": el}

    # 표본 부족 → REJECT (repeat 강제)
    assert promotion_gate(base, cand(25, n=25))["decision"] == "REJECT"
    # 성공률 후퇴(Wilson 하한) → REJECT
    assert promotion_gate(base, cand(40))["decision"] == "REJECT"
    # 성공률 유지 + 비용 하락 → PROMOTE
    assert promotion_gate(base, cand(50, cost=0.0048))["decision"] == "PROMOTE"
    # 성공률 유지 + 비용 상승 → REJECT
    assert promotion_gate(base, cand(50, cost=0.0070))["decision"] == "REJECT"
    # 비용 동률 + elapsed 단축 → PROMOTE
    assert promotion_gate(base, cand(50, el=15))["decision"] == "PROMOTE"
    # 전부 동률 → REJECT
    assert promotion_gate(base, cand(50))["decision"] == "REJECT"
    # holdout 후퇴 → 비용 하락이어도 REJECT
    assert promotion_gate(base, cand(50, cost=0.001),
                          baseline_holdout={"success_rate": 1.0},
                          candidate_holdout={"success_rate": 0.8})["decision"] == "REJECT"
    # 비용 미측정 → REJECT
    assert promotion_gate(base, {"runs": 50, "successes": 50, "success_rate": 1.0,
                                 "cost_per_success": None, "elapsed_p50": 5})["decision"] == "REJECT"
    print("RSI promotion gate self-test 통과 ✓ (표본·holdout·Wilson·비용·elapsed 8케이스)")


if __name__ == "__main__":
    _self_test()
