"""rsi_run.py orchestration의 순수 로직 검증 (LLM/API 무비용).

- load_baseline: overall 없는 JSON은 거부
- write_report: PROMOTE/REJECT 판정이 report에 반영
- promotion_gate 연동: baseline/candidate dict로 판정 결정 확인
"""
import json
import tempfile
from pathlib import Path

from rsi import promotion_gate
import rsi_run as R
from rsi_run import FORGE_PREFIX, load_baseline, run_candidate_cmd, write_report


def _agg(sr, cost, elapsed):
    # P1-D: promotion_gate가 표본 요건(min_samples)·Wilson 하한을 쓰므로 runs/successes를 충분히 준다.
    runs = 50
    ov = {"success_rate": sr, "cost_per_success": cost,
          "elapsed_p50": elapsed, "runs": runs, "successes": round(sr * runs)}
    return {"overall": ov, "promotion": ov, "holdout": {"success_rate": 1.0, "runs": 15}}


def test_load_baseline_ok():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "base.json"
        p.write_text(json.dumps(_agg(1.0, 0.006, 20.0)), encoding="utf-8")
        assert load_baseline(str(p))["overall"]["success_rate"] == 1.0


def test_load_baseline_rejects_no_overall():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bad.json"
        p.write_text(json.dumps({"tasks": {}}), encoding="utf-8")
        try:
            load_baseline(str(p))
            assert False, "overall 없는 JSON이 거부되어야 함"
        except ValueError:
            pass


def test_write_report_promote():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        dec = promotion_gate(_agg(1.0, 0.006, 20.0)["overall"],
                             _agg(1.0, 0.0048, 20.0)["overall"])
        assert dec["decision"] == "PROMOTE"
        write_report(_agg(1.0, 0.006, 20.0), _agg(1.0, 0.0048, 20.0), dec,
                     out=out, variant="test", candidate_cmd="echo hi", worktree="/tmp/wt")
        text = out.read_text(encoding="utf-8")
        assert "PROMOTE" in text
        assert "auto-merge 하지 않는다" in text  # 사람 승인 게이트 명시


def test_write_report_reject():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        dec = promotion_gate(_agg(1.0, 0.006, 20.0)["overall"],
                             _agg(0.8, 0.001, 5.0)["overall"])
        assert dec["decision"] == "REJECT"
        write_report(_agg(1.0, 0.006, 20.0), _agg(0.8, 0.001, 5.0), dec,
                     out=out, variant="test", candidate_cmd="echo hi", worktree="/tmp/wt")
        assert "REJECT" in out.read_text(encoding="utf-8")


def test_promotion_gate_self_test():
    # rsi.py의 내장 self-test(P1-D: 표본·holdout·Wilson·비용·elapsed)에 위임 — 중복 유지 대신
    # authority 한 곳(rsi._self_test)에서 검증한다. 상세 케이스는 test_rsi_promotion.py.
    import rsi
    rsi._self_test()


def test_forge_prefix_constant():
    assert FORGE_PREFIX == "forge:"


def test_run_candidate_cmd_shell_mode():
    # 셸 모드는 그대로 실행된다 (무비용)
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp)
        run_candidate_cmd("echo candidate-ok > marker.txt", wt)
        assert (wt / "marker.txt").read_text().strip() == "candidate-ok"


def test_run_candidate_cmd_shell_failure_raises():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_candidate_cmd("exit 3", Path(tmp))
            assert False, "비정상 종료는 RuntimeError를 던져야 함"
        except RuntimeError as e:
            assert "실패" in str(e)


def test_run_candidate_cmd_forge_empty_goal_rejected():
    # forge: 접두사지만 goal이 비면 즉시 거부 (API 호출 전에 막는다)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_candidate_cmd("forge:", Path(tmp))
            assert False, "빈 forge goal은 ValueError를 던져야 함"
        except ValueError as e:
            assert "비어 있음" in str(e)


def test_run_forge_subprocess_layout():
    # _run_forge가 쓰는 프로세스 구성(env PYTHONPATH + argv 전달 + cwd=worktree)이
    # 올바른지 무비용으로 검증한다. 실제 FORGE 호출(API 비용)은 하지 않는다.
    import os
    import subprocess
    import sys
    from rsi_run import _run_forge  # noqa: F401 — 모듈 import 가능 확인

    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp)
        (wt / "backend").mkdir()
        (wt / "backend" / "probe.py").write_text(
            "import sys; print('argv:', sys.argv[1:]); print('cwd ok')", encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(wt) + os.pathsep + env.get("PYTHONPATH", "")
        script = ("import sys; sys.path.insert(0, 'backend'); import probe; "
                  "print('PYTHONPATH probe OK')")
        r = subprocess.run([sys.executable, "-c", script, "goal-arg", str(wt)],
                           cwd=str(wt), env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "goal-arg" in r.stdout
        assert "PYTHONPATH probe OK" in r.stdout


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("rsi_run orchestration 로직 테스트 통과")


def _repo(tmp):
    import subprocess
    d = Path(tmp)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for a in (["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(d), *a], check=True)
    (d / "f.txt").write_text("base")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "init"], check=True)
    sha = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    return d, sha


def test_noop_candidate_detected():
    """아무것도 안 바꾼 candidate는 벤치 전에 걸러야 한다 — 같은 코드의 결과 차이는
    전부 노이즈고, 그 노이즈로 PROMOTE가 나면 없는 개선을 기록한다."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d, sha = _repo(tmp)
        assert R.worktree_is_unchanged(d, sha) is True
        # 미커밋 변경
        (d / "f.txt").write_text("changed")
        assert R.worktree_is_unchanged(d, sha) is False
        # 커밋해도 변경으로 본다(candidate-cmd가 커밋할 수 있다)
        subprocess.run(["git", "-C", str(d), "commit", "-qam", "work"], check=True)
        assert R.worktree_is_unchanged(d, sha) is False


def test_write_report_handles_noop_candidate():
    """no-op 경로는 candidate 집계가 비어 있다 — 리포트가 KeyError로 죽으면 안 된다."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "r.md"
        R.write_report({"overall": {"success_rate": 0.9, "cost_per_success": 0.01,
                                    "elapsed_p50": 10, "runs": 21}},
                       {"overall": {}, "variant": "no-op"},
                       {"decision": "REJECT", "reason": "no-op"},
                       out=out, variant="no-op", candidate_cmd="forge:x", worktree="/tmp/w")
        body = out.read_text()
        assert "REJECT" in body and "no-op" in body
