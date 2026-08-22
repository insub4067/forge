"""비용 계산·병목 진단 — 순수 함수(DB 비의존, 테스트 가능).

목표는 cost per successfully completed task를 데이터로 판단하는 것.
가격표가 없으면 비용은 None으로 두고 토큰 계측만 사용한다.
"""
from .config import MODEL_PRICING


def run_cost(model: str, cache_hit: int, cache_miss: int, completion: int) -> float | None:
    """한 role 실행 비용(USD). 가격표에 없는 모델이면 None."""
    price = MODEL_PRICING.get(model)
    if not price:
        return None
    return (
        cache_miss * price["cache_miss"]
        + cache_hit * price["cache_hit"]
        + completion * price["output"]
    ) / 1_000_000


def sum_cost(rows: list[dict]) -> tuple[float, int, int]:
    """가격표에 있는 role만 합산. (총비용, 가격산정된 run 수, 전체 run 수)."""
    total = 0.0
    priced = 0
    for r in rows:
        c = run_cost(
            r.get("model", ""),
            r.get("cache_hit_tokens", 0),
            r.get("cache_miss_tokens", 0),
            r.get("completion_tokens", 0),
        )
        if c is not None:
            total += c
            priced += 1
    return round(total, 6), priced, len(rows)


def bottlenecks(agg: dict) -> list[str]:
    """집계에서 비용 낭비 가능성이 큰 패턴을 rule로 표시(진단용 — 정책 자동 변경 없음)."""
    out: list[str] = []
    total_tokens = agg.get("prompt_tokens", 0) + agg.get("completion_tokens", 0)
    role_tokens = agg.get("role_tokens", {})
    planner = role_tokens.get("planner", 0)
    if total_tokens and planner / total_tokens > 0.40:
        out.append("Planner 토큰 비중이 40%를 넘음 — thinking effort 하향 또는 탐색 축소 후보")

    successes = agg.get("successful", 0)
    debugger_calls = agg.get("role_calls", {}).get("debugger", 0)
    if successes and debugger_calls / successes > 1.0:
        out.append("성공 세션당 Debugger가 평균 1회 초과 — 초기 코드 품질/Reviewer 기준 점검 필요")

    ratio = agg.get("cache_hit_ratio", 0)
    if total_tokens and ratio < 0.30:
        out.append("prompt cache 적중률 30% 미만 — stable prefix/요청 패턴 점검 필요")

    model_calls = agg.get("total_model_calls", 0)
    sessions = agg.get("sessions", 0)
    if sessions and model_calls / max(sessions, 1) > 20:
        out.append("세션당 model 호출이 매우 많음 — Tool Script/RPC 후보")

    return out
