"""gate 커버리지 집계 — gate 없이 코드를 바꾸고 완료한 run의 빈도를 읽는다 (G0).

`docs/proposal/gate-coverage-enforcement.md`의 미지수를 채우는 도구다. 그 run의 완료
근거는 "기존 테스트가 안 깨졌다" 하나뿐이고 요구사항 충족은 확인된 바 없다. 강제(G2)를
어떤 방식으로 넣을지는 이 숫자를 보고 정한다.

실행: ./.venv/bin/python gate_coverage.py [--since 2026-08-24] [--logs logs]
주의: 이벤트 ts는 UTC다(로컬 KST와 9시간 차).
"""
import argparse
import glob
import json
import os
from collections import Counter


def summarize(rows: list[dict]) -> dict:
    """gate_coverage 이벤트 목록 → 집계(순수 함수).

    분모는 **코드 변경이 있는 run**이다. 대화·조회 run을 섞으면 비율이 희석돼
    "대체로 괜찮다"로 오독된다.
    """
    changed = [r for r in rows if r.get("files_changed")]
    generic = [r for r in changed if r.get("generic_only")]
    cov = Counter(r.get("coverage") or "?" for r in changed)
    recovered = cov.get("recovered_gated", 0)
    # 복구가 시도된 run = 처음에 gate가 없던 run(복구 성공 + 여전히 없음)
    needed_recovery = recovered + len(generic)
    return {
        "runs": len(rows),
        "code_changing_runs": len(changed),
        "generic_only_runs": len(generic),
        "generic_only_rate": round(len(generic) / len(changed), 3) if changed else None,
        "by_coverage": dict(cov),
        # 모델이 처음부터 gate를 만든 비율 — 복구 장치 없이도 되는 비율
        "gate_missing_rate": round(needed_recovery / len(changed), 3) if changed else None,
        # 복구가 실제로 gate를 만들어 낸 비율(복구 장치의 효과)
        "recovery_success_rate": (round(recovered / needed_recovery, 3)
                                  if needed_recovery else None),
        "by_status": dict(Counter(r.get("status", "?") for r in rows)),
        "generic_only_by_status": dict(Counter(r.get("status", "?") for r in generic)),
    }


def summarize_validity(rows: list[dict]) -> dict:
    """gate_validity 이벤트 → 판별력 집계(순수 함수).

    trivial = 변경 전에도 통과하던 게이트(판별력 없음). unknown = probe를 못 돌려 모름
    (git repo가 아닌 워크스페이스). unknown은 비율 분모에서 뺀다 — 모르는 것으로 비율을
    만들면 판별력을 과대·과소 어느 쪽으로든 왜곡한다.
    """
    valid = sum(r.get("valid", 0) for r in rows)
    trivial = sum(r.get("trivial", 0) for r in rows)
    unknown = sum(r.get("unknown", 0) for r in rows)
    judged = valid + trivial
    return {
        "runs": len(rows), "valid": valid, "trivial": trivial, "unknown": unknown,
        "judged": judged,
        "trivial_rate": round(trivial / judged, 3) if judged else None,
        # probe가 아예 못 돈 비율 — 높으면 P0-A 보호가 사실상 꺼져 있다는 뜻이다
        "unknown_rate": round(unknown / (judged + unknown), 3) if (judged + unknown) else None,
    }


def is_real_session(session_id: str) -> bool:
    """실제 세션 id는 uuid4().hex(32자 hex)다. 그 형식이 아니면 테스트·합성 run이다
    (예전 테스트가 session_id="s1"로 운영 로그에 가짜 run을 쌓아 뒀다 — 지금은 막혔지만
    남은 줄이 집계에 섞이면 안 된다). 로그를 지우지 않고 읽을 때 걸러낸다."""
    sid = session_id or ""
    return len(sid) == 32 and all(c in "0123456789abcdef" for c in sid)


def load(logs_dir: str, since: str, event_type: str = "gate_coverage") -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(logs_dir, "events-*.jsonl"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != event_type:
                    continue
                if not is_real_session(e.get("session_id", "")):
                    continue
                if since and (e.get("ts") or "") < since:
                    continue
                rows.append(e.get("data") or {})
    return rows


def main():
    ap = argparse.ArgumentParser(description="gate 커버리지 집계 (G0)")
    ap.add_argument("--logs", default="logs", help="이벤트 로그 디렉터리")
    ap.add_argument("--since", default="", help="UTC ISO 접두사로 필터 (예: 2026-08-24)")
    args = ap.parse_args()

    rows = load(args.logs, args.since)
    if not rows:
        print("gate_coverage 이벤트가 없습니다. 계측 도입 이후의 run이 필요합니다.")
        return
    s = summarize(rows)
    print(f"run {s['runs']}개 (코드 변경 있는 run {s['code_changing_runs']}개)")
    print(f"경로 분포: {s['by_coverage']}")
    print(f"모델이 gate를 안 만든 비율: {s['gate_missing_rate']}"
          f"  (복구가 만들어낸 비율: {s['recovery_success_rate']})")
    print(f"복구 후에도 gate 0(요구사항 미검증): {s['generic_only_runs']}개"
          f"  비율 {s['generic_only_rate']}")
    print(f"status 분포: {s['by_status']}")
    print(f"gate 0 run의 status: {s['generic_only_by_status']}")

    # ── 게이트 판별력 (P0-A) ──
    v = summarize_validity(load(args.logs, args.since, "gate_validity"))
    if not v["runs"]:
        print("\ngate_validity 이벤트 없음 — 계측 도입 이후의 run이 필요합니다.")
        return
    print(f"\n게이트 판별력: run {v['runs']}개 · 게이트 {v['judged'] + v['unknown']}개")
    print(f"  trivial(변경 전에도 통과) {v['trivial']} / 판정가능 {v['judged']}"
          f"  비율 {v['trivial_rate']}")
    print(f"  probe 불가(git repo 아님 등) {v['unknown']}  비율 {v['unknown_rate']}"
          "  ← 높으면 trivial 탐지가 사실상 꺼져 있다")


if __name__ == "__main__":
    main()
