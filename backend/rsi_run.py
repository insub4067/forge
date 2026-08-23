"""Bounded RSI R1 — candidate worktree orchestration.

rsi.py가 '판정'만 담당한다면, 이 모듈은 그 판정을 실제로 수행하는 실행 파이프라인이다.

흐름 (R1):
  1. baseline 집계 JSON 로드 (bench.py --run --json 으로 생성된 것)
  2. candidate worktree 생성 (git worktree add, 현재 HEAD 기준)
  3. candidate-cmd 실행 — FORGE 자기수정(프롬프트/스크립트)을 worktree 안에서 적용
  4. 동일 benchmark를 worktree에서 실행 (--json 으로 candidate 집계 저장)
  5. promotion_gate(baseline, candidate) 로 판정
  6. promotion report 생성 — 사람 승인용. auto-merge 하지 않는다.

안전 원칙:
  - main을 직접 수정하지 않는다. 모든 변경은 candidate worktree 안에서만.
  - auto-merge 하지 않는다. 최종 승인은 사람이 한다(report를 보고 merge 결정).
  - candidate-cmd가 실패하면(비정상 종료) 즉시 중단하고 REJECT 처리한다.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rsi import promotion_gate

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path, *, timeout: int = 3600) -> subprocess.CompletedProcess:
    """cwd에서 명령 실행. 실패 시 CalledProcessError를 던진다."""
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def load_baseline(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "overall" not in data:
        raise ValueError(f"baseline JSON에 'overall'이 없음: {path}")
    return data


def create_worktree(base: Path) -> Path:
    """현재 HEAD 기준 candidate worktree를 임시 디렉터리에 만든다."""
    tmp = Path(tempfile.mkdtemp(prefix="rsi-candidate-"))
    _run(["git", "worktree", "add", "--detach", str(tmp), "HEAD"], base)
    return tmp


def run_candidate_cmd(cmd: str, worktree: Path) -> None:
    """candidate worktree 안에서 자기수정 명령을 실행한다.
    셸 문자열을 그대로 실행하므로, FORGE 프롬프트/스크립트를 전달할 수 있다."""
    r = subprocess.run(cmd, cwd=str(worktree), shell=True, text=True, timeout=7200)
    if r.returncode != 0:
        raise RuntimeError(f"candidate-cmd 실패 (exit {r.returncode}): {cmd}")


def run_benchmark(worktree: Path, *, repeat: int, json_path: Path, tier: str,
                  only: str = "", complex_only: bool = False) -> dict:
    """candidate worktree에서 동일 benchmark를 실행해 집계 JSON을 저장한다."""
    bench = worktree / "backend" / "bench.py"
    cmd = [sys.executable, str(bench), "--run", "--repeat", str(repeat),
           "--tier", tier, "--json", str(json_path)]
    if only:
        cmd += ["--task", only]
    if complex_only:
        cmd += ["--complex"]
    r = _run(cmd, worktree)
    if r.returncode != 0:
        raise RuntimeError(f"benchmark 실행 실패 (exit {r.returncode}):\n{r.stderr[-2000:]}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def write_report(baseline: dict, candidate: dict, decision: dict, *, out: Path,
                 variant: str, candidate_cmd: str, worktree: str) -> None:
    b, c = baseline["overall"], candidate["overall"]
    lines = [
        "# Bounded RSI R1 — Promotion Report",
        "",
        f"- variant: {variant}",
        f"- candidate-cmd: `{candidate_cmd}`",
        f"- candidate worktree: `{worktree}`",
        "",
        "## 판정",
        f"- **{decision['decision']}** — {decision['reason']}",
        "",
        "## baseline vs candidate (overall)",
        "",
        "| 지표 | baseline | candidate |",
        "|------|----------|-----------|",
        f"| success_rate | {b['success_rate']} | {c['success_rate']} |",
        f"| cost_per_success | {b.get('cost_per_success')} | {c.get('cost_per_success')} |",
        f"| elapsed_p50 | {b.get('elapsed_p50')} | {c.get('elapsed_p50')} |",
        f"| runs | {b.get('runs')} | {c.get('runs')} |",
        "",
        "## 다음 단계 (사람 승인)",
        "",
        "- **PROMOTE**: `git worktree remove <candidate>` 후, candidate 변경을 main에 수동 merge.",
        "- **REJECT**: candidate worktree 제거. main은 그대로.",
        "- 이 보고서는 자동 판정일 뿐, **auto-merge 하지 않는다.** 최종 승인은 사람이 한다.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Bounded RSI R1 — candidate worktree orchestration")
    ap.add_argument("--baseline", required=True, help="baseline 집계 JSON (bench.py --json 산출물)")
    ap.add_argument("--candidate-cmd", required=True, help="candidate worktree에서 실행할 자기수정 명령(셸)")
    ap.add_argument("--repeat", type=int, default=1, help="benchmark task당 반복 횟수")
    ap.add_argument("--tier", default="auto", help="모델 티어: auto|flash|pro|ox")
    ap.add_argument("--task", default="", help="특정 task만(쉼표 구분)")
    ap.add_argument("--complex", action="store_true", help="COMPLEX task만 실행")
    ap.add_argument("--json", default="", help="candidate 집계 JSON 저장 경로")
    ap.add_argument("--report", default="", help="promotion report 저장 경로")
    ap.add_argument("--keep", action="store_true", help="candidate worktree를 제거하지 않고 유지")
    args = ap.parse_args()

    baseline = load_baseline(args.baseline)
    print(f"baseline 로드: success_rate={baseline['overall']['success_rate']}")

    worktree = create_worktree(REPO_ROOT)
    print(f"candidate worktree: {worktree}")

    try:
        print(f"candidate-cmd 실행: {args.candidate_cmd}")
        run_candidate_cmd(args.candidate_cmd, worktree)

        cand_json = Path(args.json) if args.json else Path(tempfile.mkdtemp()) / "candidate.json"
        candidate = run_benchmark(worktree, repeat=args.repeat, json_path=cand_json,
                                  tier=args.tier, only=args.task, complex_only=args.complex)
        print(f"candidate 집계: success_rate={candidate['overall']['success_rate']}")

        decision = promotion_gate(baseline["overall"], candidate["overall"])
        print(f"판정: {decision['decision']} — {decision['reason']}")

        if args.report:
            write_report(baseline, candidate, decision, out=Path(args.report),
                         variant=candidate.get("variant", "?"), candidate_cmd=args.candidate_cmd,
                         worktree=str(worktree))
            print(f"→ report: {args.report}")
        if args.json:
            print(f"→ candidate JSON: {args.json}")
    finally:
        if not args.keep:
            _run(["git", "worktree", "remove", "--force", str(worktree)], REPO_ROOT)
            shutil.rmtree(worktree, ignore_errors=True)
            print(f"candidate worktree 정리: {worktree}")
        else:
            print(f"candidate worktree 유지(--keep): {worktree}")


if __name__ == "__main__":
    main()
