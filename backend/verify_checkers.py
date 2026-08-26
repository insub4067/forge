"""benchmark checker 자체의 correctness/idempotency 검증(무비용, LLM 없음).

FORGE가 checker로 평가받으므로 checker가 틀리면 최적화 방향도 틀어진다. 각 task에 대해:
  - Reference: setup→fix→check == PASS
  - Broken:    setup만(구현 전 상태)→check == FAIL   (already_ok task는 제외 — 정답=무변경)
  - Idempotency: setup→fix→check 두 번 == PASS, PASS
실행: cd backend && .venv/bin/python verify_checkers.py
"""
import tempfile, pathlib, shutil, sys
from bench_tasks import TASKS

def run_task(t):
    code = t["code"]; already_ok = t.get("already_ok", False)
    res = {"code": code, "already_ok": already_ok}
    # Reference: setup + fix → PASS
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        t["setup"](d); t["fix"](d)
        res["reference"] = bool(t["check"](d))
        res["idempotent"] = res["reference"] and bool(t["check"](d))  # 두 번째 실행도 PASS
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # Broken: setup만(구현 전) → FAIL 이어야 한다. already_ok는 setup이 이미 PASS라 제외.
    if not already_ok:
        d = pathlib.Path(tempfile.mkdtemp())
        try:
            t["setup"](d)
            res["broken_fails"] = not bool(t["check"](d))
        finally:
            shutil.rmtree(d, ignore_errors=True)
    else:
        res["broken_fails"] = None  # N/A
    return res

def main():
    rows = [run_task(t) for t in TASKS]
    bad = []
    for r in rows:
        ok_ref = r["reference"]
        ok_idem = r["idempotent"]
        ok_broken = (r["broken_fails"] is None) or r["broken_fails"]
        flag = "" if (ok_ref and ok_idem and ok_broken) else "  <== FAIL"
        if flag: bad.append(r["code"])
        bstr = "N/A" if r["broken_fails"] is None else str(r["broken_fails"])
        print("%-3s ref=%s idem=%s broken_fails=%s%s" % (r["code"], r["reference"], r["idempotent"], bstr, flag))
    print("\n%d/%d checker OK" % (len(rows)-len(bad), len(rows)))
    if bad:
        print("문제 task:", bad); sys.exit(1)
    print("모든 checker: reference PASS + idempotent + broken FAIL ✓")

if __name__ == "__main__":
    main()
