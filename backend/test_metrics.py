"""Agent Run Telemetry / 세션 집계 / 비용 계산 검증.

DB(Postgres)와 순수 함수 모두 확인한다. 재시작으로 ALTER가 적용된 뒤 실행:
    cd backend && PYTHONPATH=. .venv/bin/python test_metrics.py
"""
import asyncio
import uuid

from app import metrics
from app.db import store
from app.db.models import AgentRun, Session
from app.db.session import async_session


def test_pure_cost_and_bottlenecks():
    # run_cost: 알려진 모델 → 값, 미등록 모델 → None
    c = metrics.run_cost("deepseek-v4-flash", cache_hit=1_000_000, cache_miss=0, completion=0)
    assert abs(c - 0.028) < 1e-9, c
    assert metrics.run_cost("unknown-model", 100, 100, 100) is None
    # sum_cost: 미등록 모델은 제외되고 priced 카운트로 구분
    rows = [
        {"model": "deepseek-v4-flash", "cache_hit_tokens": 0, "cache_miss_tokens": 1_000_000, "completion_tokens": 0},
        {"model": "unknown", "cache_hit_tokens": 0, "cache_miss_tokens": 999, "completion_tokens": 0},
    ]
    total, priced, n = metrics.sum_cost(rows)
    assert priced == 1 and n == 2 and abs(total - 0.28) < 1e-9, (total, priced, n)
    # bottlenecks: rule 발동 확인 (pro 승격 과다 / cache 저조 / model 호출 과다)
    warns = metrics.bottlenecks({
        "prompt_tokens": 1000, "completion_tokens": 0,
        "cache_hit_ratio": 0.1,                   # < 30%
        "sessions": 2, "pro_sessions": 2,          # 100% > 50% 승격
        "total_model_calls": 100,                  # 50/session > 20
    })
    assert len(warns) == 3, warns
    print("OK pure cost/bottlenecks")


async def _seed(sid, final_status, runs):
    async with async_session() as s:
        s.add(Session(id=sid, title="metrics-test", final_status=final_status))
        for r in runs:
            s.add(AgentRun(session_id=sid, **r))
        await s.commit()


async def _cleanup(sids):
    from sqlalchemy import delete
    async with async_session() as s:
        await s.execute(delete(AgentRun).where(AgentRun.session_id.in_(sids)))
        await s.execute(delete(Session).where(Session.id.in_(sids)))
        await s.commit()


async def test_db_aggregation():
    a = "mtest-" + uuid.uuid4().hex[:8]
    b = "mtest-" + uuid.uuid4().hex[:8]
    try:
        await _seed(a, "completed", [
            dict(role="developer", model="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=50,
                 cache_hit_tokens=100, cache_miss_tokens=900, model_calls=3, tool_calls=2,
                 retries=1, compactions=1, selected_skill_count=2, selected_skills="a, b"),
            dict(role="developer", model="deepseek-v4-flash", prompt_tokens=500, completion_tokens=200,
                 cache_hit_tokens=300, cache_miss_tokens=200, model_calls=2, tool_calls=4),
            dict(role="triage", model="deepseek-v4-flash", prompt_tokens=400, completion_tokens=30,
                 cache_hit_tokens=200, cache_miss_tokens=200, model_calls=1),
        ])
        await _seed(b, "failed", [
            dict(role="developer", model="deepseek-v4-flash", prompt_tokens=800, completion_tokens=100,
                 cache_hit_tokens=0, cache_miss_tokens=800, model_calls=5, retries=2),
            dict(role="developer", model="deepseek-v4-pro", prompt_tokens=600, completion_tokens=80,
                 model_calls=4),
        ])

        # 1. completed 세션 집계
        ma = await store.session_metrics(a)
        assert ma["final_status"] == "completed"
        assert ma["total_model_calls"] == 6 and ma["total_tool_calls"] == 6
        assert ma["total_retries"] == 1 and ma["total_compactions"] == 1
        # 6. cache hit/miss 합계 + 비율
        assert ma["cache_hit_tokens"] == 600 and ma["cache_miss_tokens"] == 1300
        assert abs(ma["cache_hit_ratio"] - round(600 / 1900, 3)) < 1e-6
        # 3. Flash planner 기록 / 9. skill 기록
        assert ma["developer_calls"] == 2 and ma["pro_calls"] == 0
        assert ma["selected_skills"] == "a, b"
        # 모델별 집계: 세션 a는 전부 flash 3회
        assert ma["model_calls"].get("deepseek-v4-flash") == 3
        assert ma["model_calls"].get("deepseek-v4-pro", 0) == 0
        assert ma["model_tokens"]["deepseek-v4-flash"] == 2180

        # 2. failed 세션 집계 / Sr 승격(developer pro) / retry
        mb = await store.session_metrics(b)
        assert mb["final_status"] == "failed"
        assert mb["developer_calls"] == 2 and mb["pro_calls"] == 1
        assert mb["total_retries"] == 2
        # 모델별 집계: 세션 b는 flash 1회 + pro 1회
        assert mb["model_calls"]["deepseek-v4-flash"] == 1 and mb["model_calls"]["deepseek-v4-pro"] == 1
        assert mb["model_tokens"]["deepseek-v4-flash"] == 900
        assert mb["model_tokens"]["deepseek-v4-pro"] == 680

        # 비용: flash/pro 모두 가격표에 있으므로 priced == 전체
        runs_a = await store.session_agent_runs(a)
        cost, priced, n = metrics.sum_cost(runs_a)
        assert cost > 0 and priced == n == 3

        # 10. summary API 계층 로직 — 성공 세션에 a 포함
        summ = await store.metrics_summary()
        assert summ["successful"] >= 1
        assert 0 <= summ["success_rate"] <= 1
        assert "review_first_pass_rate" in summ and "pro_escalation_rate" in summ
        print("OK DB aggregation (completed/failed/flash/pro/debugger/cache/compaction/retry/skill/summary)")
    finally:
        await _cleanup([a, b])


if __name__ == "__main__":
    test_pure_cost_and_bottlenecks()
    asyncio.run(test_db_aggregation())
    print("\n전체 통과")
