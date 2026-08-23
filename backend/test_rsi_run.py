"""rsi_run.py orchestration의 순수 로직 검증 (LLM/API 무비용).

- load_baseline: overall 없는 JSON은 거부
- write_report: PROMOTE/REJECT 판정이 report에 반영
- promotion_gate 연동: baseline/candidate dict로 판정 결정 확인
"""
import json
import tempfile
from pathlib import Path

from rsi import promotion_gate
from rsi_run import load_baseline, write_report


def _agg(sr, cost, elapsed):
    return {"overall": {"success_rate": sr, "cost_per_success": cost,
                        "elapsed_p50": elapsed, "runs": 5, "successes": 5}}


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
    # rsi.py의 내장 self-test와 동일한 6케이스가 통과하는지
    base = {"success_rate": 1.0, "cost_per_success": 0.0060, "elapsed_p50": 20.0}
    assert promotion_gate(base, {"success_rate": 0.8, "cost_per_success": 0.001, "elapsed_p50": 5})["decision"] == "REJECT"
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0048, "elapsed_p50": 20})["decision"] == "PROMOTE"
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0070, "elapsed_p50": 5})["decision"] == "REJECT"
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0060, "elapsed_p50": 15})["decision"] == "PROMOTE"
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": 0.0060, "elapsed_p50": 20})["decision"] == "REJECT"
    assert promotion_gate(base, {"success_rate": 1.0, "cost_per_success": None, "elapsed_p50": 5})["decision"] == "REJECT"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("rsi_run orchestration 로직 테스트 통과")
