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
def aggregate(results: list[dict]) -> dict:
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
    all_elapsed = []
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
    out["overall"] = {
        "success_rate": round(tot_s / tot_n, 3) if tot_n else 0.0,
        "cost_per_success": round(tot_cost / tot_s, 6) if tot_s else None,
        "elapsed_p50": round(all_elapsed[len(all_elapsed) // 2], 1) if all_elapsed else 0.0,
        "planner_tokens": tot_ptok, "total_tokens": tot_ttok,
        "runs": tot_n, "successes": tot_s,
    }
    return out


def _variant_label() -> str:
    from app.config import settings
    parts = []
    if settings.planner_off:
        parts.append("planner=OFF")
    elif settings.planner_flash:
        parts.append("planner=FLASH")
    else:
        parts.append("planner=PRO(default)")
    if settings.skills_off:
        parts.append("skills=OFF")
    if settings.no_review:
        parts.append("review=OFF")
    if settings.coder_pro:
        parts.append("coder=PRO")
    return " ".join(parts)


def _print_report(agg: dict, variant: str):
    print(f"\n=== variant: {variant} ===")
    print(f"{'task':6} {'category':26} {'success':>9} {'cost/succ':>11} {'p50s':>6}")
    for code, t in agg["tasks"].items():
        cps = f"${t['cost_per_success']:.5f}" if t["cost_per_success"] is not None else "n/a"
        print(f"{code:6} {t['category'][:24]:26} {t['success']}/{t['n']:<7} {cps:>11} {t['elapsed_p50']:>6}")
    o = agg["overall"]
    cps = f"${o['cost_per_success']:.5f}" if o["cost_per_success"] is not None else "n/a"
    print(f"\n전체: {o['successes']}/{o['runs']} 성공  success_rate={o['success_rate']}  "
          f"cost/success={cps}  elapsed_p50={o['elapsed_p50']}s")
    print(f"planner_tokens={o['planner_tokens']:,}  total_tokens={o['total_tokens']:,}")
    print("(gate: success_rate가 baseline보다 낮으면 비용이 낮아도 탈락)")


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


async def _run_one(task: dict, idx: int, keep: bool) -> dict:
    from app.api.routes import runtime
    from app.db import store
    from app.metrics import sum_cost

    with tempfile.TemporaryDirectory(prefix=f"bench_{task['code']}_") as tmp:
        d = Path(tmp)
        task["setup"](d)
        sid = uuid.uuid4().hex
        await store.ensure_session(sid, f"bench-{task['code']}-{idx}", str(d))
        runtime.set_auto_approve(sid, True)
        history = [{"role": "user", "content": task["prompt"]}]
        await store.save_history(sid, history)
        await store.mark_running(sid, True)

        async def _emit(_evt):
            return None

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
        result = {"code": task["code"], "category": task.get("category", ""), "success": success,
                  "cost": cost if priced else None, "elapsed_s": round(elapsed, 1),
                  "planner_tok": planner_tok, "total_tok": total_tok}
    if not keep:
        await _cleanup_session(sid)
    return result


async def _run_all(repeat: int, keep: bool, only: set | None, complex_only: bool) -> dict:
    results = []
    for task in TASKS:
        if only and task["code"] not in only:
            continue
        if complex_only and not task.get("complex"):
            continue
        for i in range(repeat):
            print(f"실행: {task['code']} ({task['category']}) #{i + 1}/{repeat} …")
            results.append(await _run_one(task, i, keep))
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
    n_complex = sum(1 for t in TASKS if t.get("complex"))
    print(f"self-test 통과 ✓ (task {len(TASKS)}개 checker 전수 + 집계, COMPLEX {n_complex}개)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="실제 runtime 실행(DeepSeek API 비용 발생)")
    ap.add_argument("--repeat", type=int, default=1, help="task당 반복 횟수")
    ap.add_argument("--self-test", action="store_true", help="task checker + 집계만 검증(무비용)")
    ap.add_argument("--keep", action="store_true", help="bench 세션을 DB에 보존(기본은 정리)")
    ap.add_argument("--task", default="", help="특정 task만(쉼표 구분)")
    ap.add_argument("--complex", action="store_true", help="COMPLEX task만 실행")
    ap.add_argument("--json", default="", help="집계 결과를 이 경로에 JSON으로 저장(compare.py용)")
    args = ap.parse_args()
    if args.run:
        only = {c.strip().upper() for c in args.task.split(",") if c.strip()} or None
        agg = asyncio.run(_run_all(args.repeat, args.keep, only, args.complex))
        variant = _variant_label()
        _print_report(agg, variant)
        if args.json:
            import json
            agg["variant"] = variant
            Path(args.json).write_text(json.dumps(agg, indent=2), encoding="utf-8")
            print(f"→ 저장: {args.json}")
    else:
        _self_test()


if __name__ == "__main__":
    main()
