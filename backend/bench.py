"""R0 — 고정 benchmark 하네스 (RSI 제안 §5의 선결 조건).

목적: FORGE 변경 전/후의 success_rate와 cost_per_success를 결정적으로 측정한다.
"느낌"이 아니라 계측으로 판정하기 위한 baseline 도구.

- 각 task는 격리된 임시 fixture repo에서 실행(부작용 없음, 재현 가능).
- 채점은 결정적이어야 한다(테스트 통과·grep 매치). "모델이 잘한 것 같다" 채점 금지.
- LLM 비결정성 흡수용으로 task마다 N회 반복.
- worktree/candidate/promotion은 여기 없다(R1+). R0는 baseline 측정만.

실행:
  python bench.py --self-test        # 채점·집계 로직만 검증(LLM 호출 없음, 무비용)
  python bench.py --run [--repeat 3] # 실제 runtime 실행(DeepSeek API 비용 발생)

# ponytail: R0 = 측정만. candidate worktree·사전식 게이트·promotion은 R1에서.
"""
import argparse
import asyncio
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


# ── 고정 task: (fixture 생성, 프롬프트, 결정적 성공 판정) ────────────────────
def _setup_edit(d: Path):
    (d / "README.md").write_text("# demo\n", encoding="utf-8")

def _check_edit(d: Path) -> bool:
    return "RUN=python main.py" in (d / "README.md").read_text(encoding="utf-8", errors="replace")

def _setup_bugfix(d: Path):
    (d / "calc.py").write_text("def subtract(a, b):\n    return a + b\n", encoding="utf-8")
    (d / "test_calc.py").write_text(
        "from calc import subtract\n"
        "assert subtract(5, 3) == 2, subtract(5, 3)\n"
        "print('ok')\n",
        encoding="utf-8",
    )

def _check_bugfix(d: Path) -> bool:
    # 에이전트가 작업 중 남긴 stale 바이트코드가 채점을 오염시키지 않게 제거 후 실행.
    for pyc in d.rglob("__pycache__"):
        for f in pyc.glob("*"):
            f.unlink()
    r = subprocess.run([sys.executable, "-B", "test_calc.py"], cwd=str(d), capture_output=True, timeout=30)
    return r.returncode == 0


BENCH_TASKS = [
    {
        "code": "A",
        "kind": "단순 파일 수정",
        "prompt": "README.md 파일의 맨 끝에 정확히 다음 한 줄을 추가해줘: RUN=python main.py",
        "setup": _setup_edit,
        "check": _check_edit,
    },
    {
        "code": "B",
        "kind": "단일 버그 수정",
        "prompt": "test_calc.py가 통과하도록 calc.py의 subtract 함수를 고쳐줘. 지금 뺄셈이 아니라 덧셈을 한다.",
        "setup": _setup_bugfix,
        "check": _check_bugfix,
    },
]


# ── 집계 (순수 함수 — self-test 대상, LLM 무관) ──────────────────────────────
def aggregate(results: list[dict]) -> dict:
    """task별 run 결과 리스트 → success_rate / cost_per_success / elapsed_p50."""
    by_task: dict[str, dict] = {}
    for r in results:
        t = by_task.setdefault(r["code"], {"n": 0, "success": 0, "cost": 0.0, "elapsed": []})
        t["n"] += 1
        if r["success"]:
            t["success"] += 1
        if r["cost"] is not None:
            t["cost"] += r["cost"]
        t["elapsed"].append(r["elapsed_s"])
    out = {"tasks": {}, "overall": {}}
    tot_n = tot_s = 0
    tot_cost = 0.0
    for code, t in by_task.items():
        sr = t["success"] / t["n"] if t["n"] else 0.0
        cps = (t["cost"] / t["success"]) if t["success"] else None
        el = sorted(t["elapsed"])
        p50 = el[len(el) // 2] if el else 0.0
        out["tasks"][code] = {"success_rate": round(sr, 3), "cost_per_success": cps,
                              "elapsed_p50": round(p50, 1), "n": t["n"], "success": t["success"]}
        tot_n += t["n"]; tot_s += t["success"]; tot_cost += t["cost"]
    out["overall"] = {
        "success_rate": round(tot_s / tot_n, 3) if tot_n else 0.0,
        "cost_per_success": round(tot_cost / tot_s, 6) if tot_s else None,
        "runs": tot_n, "successes": tot_s,
    }
    return out


def _print_report(agg: dict):
    print(f"\n{'task':6} {'success':>10} {'cost/success':>14} {'elapsed_p50':>12}")
    for code, t in agg["tasks"].items():
        cps = f"${t['cost_per_success']:.5f}" if t["cost_per_success"] is not None else "n/a"
        print(f"{code:6} {t['success']}/{t['n']:<8} {cps:>14} {t['elapsed_p50']:>10}s")
    o = agg["overall"]
    cps = f"${o['cost_per_success']:.5f}" if o["cost_per_success"] is not None else "n/a"
    print(f"{'전체':6} {o['successes']}/{o['runs']:<8} {cps:>14}")
    print(f"\nsuccess_rate={o['success_rate']}  (성공률이 baseline보다 낮으면 비용이 낮아도 candidate 탈락)")


# ── 실제 실행 (LLM 비용 발생 — --run 에서만 진입) ────────────────────────────
async def _run_one(task: dict, idx: int) -> dict:
    from app.api.routes import runtime  # 지연 import — self-test는 이 경로를 안 탄다
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

        # 결정적 성공 판정 — final_status가 아니라 실제 결과물로 채점(제안 §5.1)
        try:
            success = bool(task["check"](d))
        except Exception:
            success = False
        rows = await store.session_agent_runs(sid)
        cost, priced, total = sum_cost(rows)
        return {"code": task["code"], "success": success, "cost": cost if priced else None,
                "elapsed_s": round(elapsed, 1)}


async def _run_all(repeat: int) -> dict:
    results = []
    for task in BENCH_TASKS:
        for i in range(repeat):
            print(f"실행: task {task['code']} ({task['kind']}) #{i + 1}/{repeat} …")
            results.append(await _run_one(task, i))
    return aggregate(results)


# ── self-test: 채점·집계 로직만 (LLM 없음, 무비용) ───────────────────────────
def _self_test():
    # check 함수가 fixture에서 결정적으로 동작하는지
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _setup_edit(d)
        assert _check_edit(d) is False, "수정 전 실패해야"
        (d / "README.md").write_text("# demo\nRUN=python main.py\n", encoding="utf-8")
        assert _check_edit(d) is True, "수정 후 성공해야"
        _setup_bugfix(d)
        assert _check_bugfix(d) is False, "버그 상태 실패해야"
        (d / "calc.py").write_text("def subtract(a, b):\n    return a - b\n", encoding="utf-8")
        assert _check_bugfix(d) is True, "수정 후 성공해야"
    # 집계 산식
    synth = [
        {"code": "A", "success": True, "cost": 0.010, "elapsed_s": 5.0},
        {"code": "A", "success": False, "cost": 0.008, "elapsed_s": 6.0},
        {"code": "B", "success": True, "cost": 0.100, "elapsed_s": 20.0},
    ]
    agg = aggregate(synth)
    assert agg["tasks"]["A"]["success_rate"] == 0.5, agg
    assert abs(agg["tasks"]["A"]["cost_per_success"] - 0.018) < 1e-9, agg  # 성공 1건에 총비용 귀속
    assert agg["overall"]["successes"] == 2 and agg["overall"]["runs"] == 3, agg
    assert abs(agg["overall"]["cost_per_success"] - (0.118 / 2)) < 1e-9, agg
    print("self-test 통과 ✓ (결정적 채점 + 집계 산식)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="실제 runtime 실행(DeepSeek API 비용 발생)")
    ap.add_argument("--repeat", type=int, default=1, help="task당 반복 횟수")
    ap.add_argument("--self-test", action="store_true", help="채점·집계만 검증(무비용)")
    args = ap.parse_args()
    if args.run:
        agg = asyncio.run(_run_all(args.repeat))
        _print_report(agg)
    else:
        _self_test()


if __name__ == "__main__":
    main()
