"""R0 — 고정 benchmark 하네스 (RSI 제안 §5의 선결 조건).

목적: FORGE 변경 전/후의 success_rate·cost_per_success·elapsed를 결정적으로 측정한다.
"느낌"이 아니라 계측으로 판정하기 위한 baseline 도구.

- task 정의·checker는 bench_tasks.py(격리 fixture + 결정적 채점). LLM 판정 금지.
- LLM 비결정성 흡수용으로 task마다 N회 반복.
- worktree/candidate/promotion은 여기 없다(R1+). R0는 baseline 측정만.
- 실험 축은 env 플래그로 준다(무비용, 코드 무변경):
    FORGE_PLANNER_FLASH=1  COMPLEX planner를 flash로
    FORGE_PLANNER_OFF=1    COMPLEX에서 planner 생략
    FORGE_SKILLS_OFF=1     skill 주입 비활성

실행:
  python bench.py --self-test         # task checker + 집계 검증(LLM 없음, 무비용)
  python bench.py --run [--repeat 3]  # 실제 runtime 실행(DeepSeek API 비용 발생)
  python bench.py --run --complex     # complex task만(planner 실험용)
  python bench.py --run --task C,D    # 특정 task만
"""
import argparse
import asyncio
import tempfile
import time
import uuid
from pathlib import Path

from bench_tasks import TASKS


# ── 집계 (순수 함수 — self-test 대상, LLM 무관) ──────────────────────────────
def _pct(x: int, n: int) -> float:
    return round(x / n, 3) if n else 0.0


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return round(sorted_vals[i], 1)


# FORGE가 '완료'라고 선언한 상태(요구사항이 됐다고 주장). deterministic checker와 대조해
# verified/false를 가린다. completed=gate 검증까지 통과, completed_unverified=완료했으나 gate 미검증.
_COMPLETED_STATES = {"completed", "completed_unverified"}


def aggregate(results: list[dict]) -> dict:
    """deterministic checker(정답)와 FORGE 완료 상태를 대조해 verified/false 지표를 낸다.
    가장 중요한 3지표: verified_success_rate, false_completion_rate, cost_per_verified_task.
    토큰 절감 자체는 성공이 아니다 — verified success 대비 비용으로만 판단한다."""
    by_task: dict[str, dict] = {}
    for r in results:
        t = by_task.setdefault(r["code"], {"n": 0, "success": 0, "cost": 0.0, "elapsed": [],
                                           "planner_tok": 0, "total_tok": 0, "category": r.get("category", "")})
        t["n"] += 1
        if r["success"]:
            t["success"] += 1
        if r["cost"] is not None:
            t["cost"] += r["cost"]
        t["elapsed"].append(r["elapsed_s"])
        t["planner_tok"] += r.get("planner_tok", 0)
        t["total_tok"] += r.get("total_tok", 0)
    out = {"tasks": {}, "overall": {}}
    tot_n = tot_s = 0
    tot_cost = 0.0
    tot_ptok = tot_ttok = 0
    all_elapsed: list[float] = []
    for code, t in by_task.items():
        sr = t["success"] / t["n"] if t["n"] else 0.0
        cps = (t["cost"] / t["success"]) if t["success"] else None
        el = sorted(t["elapsed"])
        out["tasks"][code] = {"category": t["category"], "success_rate": round(sr, 3),
                              "cost_per_success": cps, "elapsed_p50": round(el[len(el) // 2], 1) if el else 0.0,
                              "n": t["n"], "success": t["success"]}
        tot_n += t["n"]; tot_s += t["success"]; tot_cost += t["cost"]
        tot_ptok += t["planner_tok"]; tot_ttok += t["total_tok"]; all_elapsed += t["elapsed"]
    all_elapsed.sort()

    # ── confusion matrix: FORGE 완료 주장 × deterministic checker(정답) ──
    def fs(r):
        return r.get("forge_status")
    verified_success = sum(1 for r in results if r["success"] and fs(r) in _COMPLETED_STATES)
    false_completion = sum(1 for r in results if not r["success"] and fs(r) in _COMPLETED_STATES)
    false_failure = sum(1 for r in results if r["success"] and fs(r) == "verification_failed")
    n_completed = sum(1 for r in results if fs(r) == "completed")
    n_completed_unverified = sum(1 for r in results if fs(r) == "completed_unverified")
    n_verification_failed = sum(1 for r in results if fs(r) == "verification_failed")

    prompt_tok = sum(r.get("prompt_tok", 0) for r in results)
    completion_tok = sum(r.get("completion_tok", 0) for r in results)
    cache_hit = sum(r.get("cache_hit", 0) for r in results)
    cache_miss = sum(r.get("cache_miss", 0) for r in results)
    tool_calls = sum(r.get("tool_calls", 0) for r in results)
    interventions = sum(r.get("approvals", 0) for r in results)
    pro_escalated = sum(1 for r in results if r.get("pro_escalated"))
    context_blocked = sum(1 for r in results if fs(r) == "context_blocked")
    repaired = sum(1 for r in results if r.get("repaired"))
    repaired_ok = sum(1 for r in results if r.get("repaired") and r["success"] and fs(r) in _COMPLETED_STATES)

    out["overall"] = {
        # 하위 호환(기존 필드 유지)
        "success_rate": _pct(tot_s, tot_n),
        "cost_per_success": round(tot_cost / tot_s, 6) if tot_s else None,
        "elapsed_p50": _percentile(all_elapsed, 0.5),
        "planner_tokens": tot_ptok, "total_tokens": tot_ttok,
        "runs": tot_n, "successes": tot_s,
        # ── 신뢰성 핵심 3지표 ──
        "verified_success_rate": _pct(verified_success, tot_n),
        "false_completion_rate": _pct(false_completion, tot_n),
        "cost_per_verified_task": round(tot_cost / verified_success, 6) if verified_success else None,
        # ── confusion / 상태 분해 ──
        "false_failure_rate": _pct(false_failure, tot_n),
        "total_tasks": tot_n,
        "verified_success": verified_success,
        "false_completion": false_completion,
        "false_failure": false_failure,
        "completed": n_completed,
        "completed_unverified": n_completed_unverified,
        "verification_failed": n_verification_failed,
        # ── 운영 지표 ──
        "repair_rate": _pct(repaired, tot_n),
        "repair_success_rate": _pct(repaired_ok, repaired) if repaired else 0.0,
        "pro_escalation_rate": _pct(pro_escalated, tot_n),
        "context_block_rate": _pct(context_blocked, tot_n),
        "human_interventions_per_task": round(interventions / tot_n, 3) if tot_n else 0.0,
        "tool_calls_per_task": round(tool_calls / tot_n, 2) if tot_n else 0.0,
        "elapsed_avg": round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0,
        "elapsed_p95": _percentile(all_elapsed, 0.95),
        # ── 토큰·비용 ──
        "prompt_tokens": prompt_tok,
        "completion_tokens": completion_tok,
        "cache_hit_tokens": cache_hit,
        "cache_miss_tokens": cache_miss,
        "total_cost": round(tot_cost, 6),
        "cost_per_task": round(tot_cost / tot_n, 6) if tot_n else None,
    }

    # ── RSI 승격 판정용 분리 집계(P1-D): promotion set(판정용)과 holdout(판정에 절대 안 씀) ──
    # overall은 하위호환으로 전체(25태스크) 유지. promotion_gate는 아래 promotion/holdout을 쓴다.
    from rsi import is_holdout

    def _subset(keep) -> dict:
        rs = [r for r in results if keep(r["code"])]
        n = len(rs)
        s = sum(1 for r in rs if r["success"])
        cost = sum(r["cost"] for r in rs if r.get("cost") is not None)
        el = sorted(r["elapsed_s"] for r in rs)
        return {"runs": n, "successes": s, "success_rate": _pct(s, n),
                "cost_per_success": round(cost / s, 6) if s else None,
                "elapsed_p50": _percentile(el, 0.5)}

    out["promotion"] = _subset(lambda c: not is_holdout(c))
    out["holdout"] = _subset(is_holdout)
    return out


def _variant_label() -> str:
    from app.config import settings
    parts = ["developer=PRO(always)" if settings.developer_pro else "developer=FLASH+think(Jr→Sr)"]
    if settings.skills_off:
        parts.append("skills=OFF")
    return " ".join(parts)


def _print_report(agg: dict, variant: str):
    print(f"\n=== variant: {variant} ===")
    print(f"{'task':6} {'category':26} {'success':>9} {'cost/succ':>11} {'p50s':>6}")
    for code, t in agg["tasks"].items():
        cps = f"${t['cost_per_success']:.5f}" if t["cost_per_success"] is not None else "n/a"
        print(f"{code:6} {t['category'][:24]:26} {t['success']}/{t['n']:<7} {cps:>11} {t['elapsed_p50']:>6}")
    o = agg["overall"]
    cpv = f"${o['cost_per_verified_task']:.5f}" if o.get("cost_per_verified_task") is not None else "n/a"
    print("\n── 신뢰성 핵심 ──")
    print(f"verified_success_rate = {o['verified_success_rate']}  "
          f"({o['verified_success']}/{o['total_tasks']})")
    print(f"false_completion_rate = {o['false_completion_rate']}  "
          f"(완료 주장했으나 checker 실패 {o['false_completion']}건 — 가장 위험)")
    print(f"cost_per_verified_task = {cpv}")
    print(f"false_failure_rate    = {o['false_failure_rate']}  (실제로 됐는데 실패로 판정 {o['false_failure']}건)")
    print(f"\n상태: completed={o['completed']} completed_unverified={o['completed_unverified']} "
          f"verification_failed={o['verification_failed']} context_blocked={o['context_block_rate']}")
    print(f"repair_rate={o['repair_rate']} pro_escalation_rate={o['pro_escalation_rate']} "
          f"intervention/task={o['human_interventions_per_task']} tool_calls/task={o['tool_calls_per_task']}")
    print(f"elapsed avg/p50/p95 = {o['elapsed_avg']}/{o['elapsed_p50']}/{o['elapsed_p95']}s")
    print(f"tokens prompt/completion = {o['prompt_tokens']:,}/{o['completion_tokens']:,}  "
          f"cache hit/miss = {o['cache_hit_tokens']:,}/{o['cache_miss_tokens']:,}")
    print(f"total_cost=${o['total_cost']:.5f}  cost_per_task="
          f"{('$%.5f' % o['cost_per_task']) if o['cost_per_task'] is not None else 'n/a'}")
    print("(gate: verified_success_rate가 baseline보다 낮으면 비용이 낮아도 탈락. 토큰 절감≠성공)")


# ── 실제 실행 (LLM 비용 발생 — --run 에서만 진입) ────────────────────────────
async def _cleanup_session(sid: str):
    from sqlalchemy import delete
    from app.db import store
    from app.db.session import async_session
    from app.db.models import AgentRun
    async with async_session() as s:
        await s.execute(delete(AgentRun).where(AgentRun.session_id == sid))
        await s.commit()
    await store.delete_room(sid)


async def _run_one(task: dict, idx: int, keep: bool, tier: str = "auto") -> dict:
    from app.api.routes import runtime
    from app.db import store
    from app.metrics import sum_cost

    with tempfile.TemporaryDirectory(prefix=f"bench_{task['code']}_") as tmp:
        d = Path(tmp)
        task["setup"](d)
        sid = uuid.uuid4().hex
        await store.ensure_session(sid, f"bench-{task['code']}-{idx}", str(d))
        runtime.set_auto_approve(sid, True)
        runtime.set_model_tier(sid, tier)  # 모델 비교용: auto|flash|pro|ox
        history = [{"role": "user", "content": task["prompt"]}]
        await store.save_history(sid, history)
        await store.mark_running(sid, True)

        captured = {"status": None, "approvals": 0}

        async def _emit(evt):
            # FORGE의 최종 완료 상태와 개입(승인 요청) 수를 캡처해 verified/false 지표에 쓴다.
            et = evt.get("type") if isinstance(evt, dict) else None
            if et == "done":
                captured["status"] = (evt.get("data") or {}).get("status")
            elif et == "approval_request":
                captured["approvals"] += 1

        t0 = time.monotonic()
        try:
            new_history = await runtime.run(history, _emit, sid, str(d))
            await store.save_history(sid, new_history)
        except Exception as err:
            print(f"  [{task['code']}#{idx}] run 오류: {err}")
        finally:
            await store.mark_running(sid, False)
            runtime.cleanup_session(sid)
        elapsed = time.monotonic() - t0

        try:
            success = bool(task["check"](d))
        except Exception:
            success = False
        rows = await store.session_agent_runs(sid)
        cost, priced, _ = sum_cost(rows)
        planner_tok = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows if r["role"] == "planner")
        total_tok = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows)
        prompt_tok = sum(r.get("prompt_tokens", 0) for r in rows)
        completion_tok = sum(r.get("completion_tokens", 0) for r in rows)
        cache_hit = sum(r.get("cache_hit_tokens", 0) for r in rows)
        cache_miss = sum(r.get("cache_miss_tokens", 0) for r in rows)
        tool_calls = sum(r.get("tool_calls", 0) for r in rows)
        # pro 승격: developer 역할이 pro 모델로 실행됐는지(flash 단독으로 못 풀어 승격한 신호).
        pro_escalated = any(r["role"] == "developer" and "pro" in (r.get("model") or "") for r in rows)
        result = {"code": task["code"], "category": task.get("category", ""), "success": success,
                  "cost": cost if priced else None, "elapsed_s": round(elapsed, 1),
                  "planner_tok": planner_tok, "total_tok": total_tok,
                  "forge_status": captured["status"], "approvals": captured["approvals"],
                  "prompt_tok": prompt_tok, "completion_tok": completion_tok,
                  "cache_hit": cache_hit, "cache_miss": cache_miss,
                  "tool_calls": tool_calls, "pro_escalated": pro_escalated,
                  "session_id": sid}  # keep=True일 때 실패 chain을 이 세션에서 조회한다.
    if not keep:
        await _cleanup_session(sid)
    return result


async def _run_all(repeat: int, keep: bool, only: set | None, complex_only: bool,
                   tier: str = "auto") -> dict:
    results = []
    for task in TASKS:
        if only and task["code"] not in only:
            continue
        if complex_only and not task.get("complex"):
            continue
        for i in range(repeat):
            print(f"실행: {task['code']} ({task['category']}) [{tier}] #{i + 1}/{repeat} …")
            results.append(await _run_one(task, i, keep, tier))
    return aggregate(results)


# ── self-test: task checker 전수 + 집계 (LLM 없음, 무비용) ────────────────────
def _self_test():
    # 모든 task의 품질 검증: 미수정 fixture에서 check==False(false positive 없음),
    # 정답(fix) 적용 후 check==True(checker 유효). 이게 benchmark 신뢰의 핵심.
    for task in TASKS:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            task["setup"](d)
            if task.get("already_ok"):
                # 정답이 '변경 없음'인 task: 시작부터 통과해야 하고, 고의로 깨면 checker가 잡아야 한다.
                assert task["check"](d) is True, f"[{task['code']}] already_ok인데 시작부터 실패"
                task["break_it"](d)
                assert task["check"](d) is False, f"[{task['code']}] 잘못된 답을 checker가 못 잡음(느슨)"
            else:
                assert task["check"](d) is False, f"[{task['code']}] 미수정 fixture가 이미 통과(정답 노출/false positive)"
                task["fix"](d)
                assert task["check"](d) is True, f"[{task['code']}] 정답 적용 후에도 실패(checker 과도하게 엄격/깨짐)"
    # 집계 산식
    synth = [
        {"code": "A", "category": "x", "success": True, "cost": 0.010, "elapsed_s": 5.0},
        {"code": "A", "category": "x", "success": False, "cost": 0.008, "elapsed_s": 6.0},
        {"code": "B", "category": "y", "success": True, "cost": 0.100, "elapsed_s": 20.0, "planner_tok": 100, "total_tok": 300},
    ]
    agg = aggregate(synth)
    assert agg["tasks"]["A"]["success_rate"] == 0.5, agg
    assert abs(agg["tasks"]["A"]["cost_per_success"] - 0.018) < 1e-9, agg
    assert agg["overall"]["successes"] == 2 and agg["overall"]["runs"] == 3, agg
    assert abs(agg["overall"]["cost_per_success"] - (0.118 / 2)) < 1e-9, agg
    assert agg["overall"]["planner_tokens"] == 100 and agg["overall"]["total_tokens"] == 300, agg

    # ── confusion matrix 산식 검증(verified/false 지표) ──
    conf = aggregate([
        # checker PASS + FORGE completed → verified success
        {"code": "T", "category": "c", "success": True, "cost": 0.01, "elapsed_s": 5.0,
         "forge_status": "completed", "prompt_tok": 10, "completion_tok": 2, "tool_calls": 3},
        # checker FAIL + FORGE completed → FALSE COMPLETION(gate가 잘못 통과 — 최악)
        {"code": "T", "category": "c", "success": False, "cost": 0.02, "elapsed_s": 6.0,
         "forge_status": "completed", "pro_escalated": True},
        # checker PASS + FORGE verification_failed → false failure(과소평가)
        {"code": "T", "category": "c", "success": True, "cost": 0.03, "elapsed_s": 7.0,
         "forge_status": "verification_failed"},
        # checker PASS + completed_unverified → verified success(완료 주장이므로)
        {"code": "T", "category": "c", "success": True, "cost": 0.04, "elapsed_s": 8.0,
         "forge_status": "completed_unverified", "approvals": 1},
    ])
    o = conf["overall"]
    assert o["total_tasks"] == 4, o
    assert o["verified_success"] == 2 and o["verified_success_rate"] == 0.5, o
    assert o["false_completion"] == 1 and o["false_completion_rate"] == 0.25, o
    assert o["false_failure"] == 1 and o["false_failure_rate"] == 0.25, o
    assert o["completed"] == 2 and o["completed_unverified"] == 1 and o["verification_failed"] == 1, o
    # cost_per_verified_task = 총비용 / verified success 수 = 0.10 / 2
    assert abs(o["cost_per_verified_task"] - (0.10 / 2)) < 1e-9, o
    assert o["pro_escalation_rate"] == 0.25 and o["human_interventions_per_task"] == 0.25, o
    assert o["tool_calls_per_task"] == round(3 / 4, 2), o
    assert o["prompt_tokens"] == 10 and o["completion_tokens"] == 2, o
    # verified success가 0이면 cost_per_verified_task는 None(허위 정밀도 금지)
    z = aggregate([{"code": "Z", "category": "c", "success": False, "cost": 0.05,
                    "elapsed_s": 1.0, "forge_status": "verification_failed"}])
    assert z["overall"]["cost_per_verified_task"] is None, z

    n_complex = sum(1 for t in TASKS if t.get("complex"))
    print(f"self-test 통과 ✓ (task {len(TASKS)}개 checker 전수 + 집계 + confusion matrix, "
          f"COMPLEX {n_complex}개)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="실제 runtime 실행(DeepSeek API 비용 발생)")
    ap.add_argument("--repeat", type=int, default=1, help="task당 반복 횟수")
    ap.add_argument("--self-test", action="store_true", help="task checker + 집계만 검증(무비용)")
    ap.add_argument("--keep", action="store_true", help="bench 세션을 DB에 보존(기본은 정리)")
    ap.add_argument("--task", default="", help="특정 task만(쉼표 구분)")
    ap.add_argument("--complex", action="store_true", help="COMPLEX task만 실행")
    ap.add_argument("--json", default="", help="집계 결과를 이 경로에 JSON으로 저장(compare.py용)")
    ap.add_argument("--tier", default="auto", help="모델 티어: auto|flash|pro|ox (모델 비교용)")
    args = ap.parse_args()
    if args.run:
        only = {c.strip().upper() for c in args.task.split(",") if c.strip()} or None
        agg = asyncio.run(_run_all(args.repeat, args.keep, only, args.complex, args.tier))
        variant = _variant_label()
        _print_report(agg, variant)
        if args.json:
            import json
            from app.config import settings
            agg["variant"] = variant
            # P1-E: 측정 실행 경계를 기록한다 — 다른 sandbox 모드에서 잰 성공률은 이전되지 않으므로
            # 승격 판정이 baseline/candidate의 모드를 대조해 다르면 거부할 수 있게 한다.
            agg["sandbox_mode"] = settings.sandbox_mode
            Path(args.json).write_text(json.dumps(agg, indent=2), encoding="utf-8")
            print(f"→ 저장: {args.json}")
    else:
        _self_test()


if __name__ == "__main__":
    main()
