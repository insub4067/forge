"""벤치 기준선 러너 — machine-readable 아티팩트 + 실패 chain 추출.

bench._run_one(keep=True)을 그대로 오케스트레이션한다(로직 중복 아님). 산출:
  bench-results/<date>-<sha>/
    summary.json      — aggregate() 전체 지표
    runs.jsonl        — per-run 원시 결과(재현·재집계용)
    failures.json     — 실패별 root-cause chain(요구사항→gate→변경파일→검증→완료→checker)
    environment.json  — commit/timestamp/python/node/model/tier/task_ir/sandbox/auto_approve

실행: cd backend && SANDBOX_MODE=host .venv/bin/python bench_baseline.py --repeat 3 --sha <sha>
실패 chain 추출 후 kept 세션을 정리한다(telemetry 오염 방지).
"""
import argparse
import asyncio
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import bench
from bench_tasks import TASKS
from app.config import settings
from app.db import store


LOG_DIR = Path(os.environ.get("FORGE_LOG_DIR") or Path(__file__).resolve().parent / "logs")


def _events_for(session_id: str) -> list[dict]:
    """오늘 eventlog에서 이 세션의 이벤트를 읽는다(task_ir/traceability/gate_coverage 등)."""
    out = []
    for f in sorted(LOG_DIR.glob("events-*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if session_id[:12] in line:
                    try:
                        e = json.loads(line)
                        if e.get("session_id") == session_id:
                            out.append(e)
                    except Exception:
                        pass
        except Exception:
            pass
    return out


def _categorize(chain: dict) -> str:
    """false completion root cause를 chain 증거로 분류(heuristic — 수동 확인용 라벨)."""
    fs = chain["forge_status"]
    checker = chain["checker_pass"]
    gates = chain["gates"]
    reqs = chain["requirements"]
    n_gates = len(gates)
    n_passed = sum(1 for g in gates if g.get("status") == "passed")
    # false failure: FORGE는 실패라는데 checker는 PASS
    if fs == "verification_failed" and checker:
        return "GATE_EXECUTION_ERROR"  # 대개 gate 명령이 정상 코드를 잘못 막음
    # false completion: FORGE는 완료라는데 checker FAIL
    if fs in ("completed", "completed_unverified") and not checker:
        if not reqs:
            return "TASK_IR_ERROR"          # 요구사항이 안 뽑힘
        if n_gates == 0:
            return "GATE_GENERATION_ERROR"  # gate를 안 만듦 → generic만으로 통과
        if n_passed and checker is False:
            # gate는 passed인데 checker FAIL → gate가 실제 요구를 대표 못 함
            return "GATE_GENERATION_ERROR"
        return "GENERIC_VERIFICATION_ERROR"
    return "UNKNOWN"


async def _extract_chain(r: dict) -> dict:
    """실패 run 하나의 전체 chain을 세션에서 조회한다."""
    sid = r["session_id"]
    evs = _events_for(sid)
    task_ir = next((e["data"].get("task_ir") for e in evs if e.get("type") == "task_ir"), None)
    trace = next((e["data"] for e in reversed(evs) if e.get("type") == "traceability"), None)
    gcov = next((e["data"] for e in reversed(evs) if e.get("type") == "gate_coverage"), None)
    try:
        gates = await store.list_gates(sid)
    except Exception:
        gates = []
    chain = {
        "task": r["code"], "category": r["category"], "session_id": sid,
        "forge_status": r.get("forge_status"), "checker_pass": r["success"],
        "requirements": (task_ir or {}).get("requirements", []) if task_ir else [],
        "task_ir_intent": (task_ir or {}).get("intent") if task_ir else None,
        "gates": [{"title": g.get("title"), "status": g.get("status"),
                   "requirement_id": g.get("requirement_id", ""),
                   "failure_reason": g.get("failure_reason", ""),
                   "evidence": str(g.get("evidence", ""))[:300]} for g in gates],
        "gate_coverage": gcov,
        "traceability": trace,
        "cost": r.get("cost"), "elapsed_s": r.get("elapsed_s"),
        "tool_calls": r.get("tool_calls"), "approvals": r.get("approvals"),
    }
    chain["root_cause_category"] = _categorize(chain)
    return chain


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--sha", default="unknown")
    ap.add_argument("--tier", default="auto")
    ap.add_argument("--tasks", default="", help="특정 task code만(쉼표) — 스모크용")
    args = ap.parse_args()
    only = set(c.strip() for c in args.tasks.split(",") if c.strip())

    stamp = datetime.now(timezone.utc)
    date = stamp.strftime("%Y-%m-%d")
    outdir = Path("bench-results") / f"{date}-{args.sha}"
    outdir.mkdir(parents=True, exist_ok=True)

    results = []
    runs_path = outdir / "runs.jsonl"
    with runs_path.open("w", encoding="utf-8") as rf:
        for task in TASKS:
            if only and task["code"] not in only:
                continue
            for i in range(args.repeat):
                print(f"실행: {task['code']} ({task.get('category','')}) #{i+1}/{args.repeat} …", flush=True)
                r = await bench._run_one(task, i, keep=True, tier=args.tier)
                results.append(r)
                rf.write(json.dumps(r, ensure_ascii=False) + "\n")
                rf.flush()

    agg = bench.aggregate(results)
    (outdir / "summary.json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")

    # 실패(false completion + false failure) chain 추출
    failures = []
    for r in results:
        fs = r.get("forge_status")
        is_false_completion = (not r["success"]) and fs in ("completed", "completed_unverified")
        is_false_failure = r["success"] and fs == "verification_failed"
        if is_false_completion or is_false_failure:
            failures.append(await _extract_chain(r))
    (outdir / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ver(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return "unknown"

    env = {
        "commit_sha": args.sha,
        "timestamp": stamp.isoformat(),
        "python_version": platform.python_version(),
        "node_version": _ver(["node", "--version"]),
        "model": "deepseek-v4 (flash/pro auto)",
        "model_tier": args.tier,
        "task_ir_enabled": settings.task_ir_enabled,
        "sandbox_mode": settings.sandbox_mode,
        "auto_approve": True,  # bench는 무인 실행이라 세션마다 auto_approve on
        "benchmark_version": "R0-25tasks",
        "repeat": args.repeat,
        "total_runs": len(results),
    }
    (outdir / "environment.json").write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")

    # kept 세션 정리 — chain 추출이 끝났으니 telemetry 오염 방지로 지운다.
    for r in results:
        try:
            await bench._cleanup_session(r["session_id"])
        except Exception:
            pass

    o = agg["overall"]
    print("\n=== 기준선 요약 ===")
    print(f"runs={o['total_tasks']} verified_success={o['verified_success_rate']} "
          f"false_completion={o['false_completion_rate']} false_failure={o['false_failure_rate']}")
    print(f"completed={o['completed']} completed_unverified={o['completed_unverified']} "
          f"verification_failed={o['verification_failed']}")
    print(f"cost_per_verified={o['cost_per_verified_task']} intervention/task={o['human_interventions_per_task']} "
          f"tool_calls/task={o['tool_calls_per_task']}")
    print(f"failures 기록: {len(failures)}건 → {outdir}/failures.json")
    print(f"아티팩트: {outdir}/")


if __name__ == "__main__":
    asyncio.run(main())
