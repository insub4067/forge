"""에이전트 실행 로그를 run 단위로 요약·점검한다(읽기 전용, LLM 없음).

eventlog(JSONL)에는 모든 동작이 남지만 사람이 읽기엔 흩어져 있다. 여기서는 done 이벤트를
경계로 run을 복원해 "무엇을 했고, 검증했고, 커밋했는가"를 한 줄로 만들고, 프로세스가
이상하게 끝난 run에 flag를 단다. 판정은 전부 결정적 규칙 — LLM 판단은 쓰지 않는다.

  python review.py                     # 오늘 run 요약
  python review.py --flags             # 이상 징후가 있는 run만
  python review.py --session <id>      # 특정 방
  python review.py --days 3 --verbose  # 3일치 + 도구 목록
  python review.py --self-test         # 파서·규칙 검증(로그 불필요)
"""
import argparse
import collections
import datetime
import glob
import json
import os
import sys

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
# 결정적 테스트가 쓰는 가짜 세션 — 통계·점검 대상이 아니다.
TEST_SESSIONS = {"s1", "refine-selftest", "task-identity-selftest", ""}
STALL_SECONDS = 120        # 이벤트가 이만큼 끊기면 모델 대기로 본다
MANY_FILES = 3             # 태스크 없이 이만큼 고치면 계획 없이 뭉갠 것


def load_events(days: int) -> list[dict]:
    since = datetime.date.today() - datetime.timedelta(days=days - 1)
    rows = []
    for path in sorted(glob.glob(os.path.join(LOG_DIR, "events-*.jsonl"))):
        stamp = os.path.basename(path)[7:15]
        try:
            if datetime.datetime.strptime(stamp, "%Y%m%d").date() < since:
                continue
        except ValueError:
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def live_sessions() -> set | None:
    """DB에 남아 있는 방 id. bench는 끝나고 방을 지우므로 이걸로 벤치 run이 걸러진다.
    DB에 못 붙으면 None — 필터 없이 전체를 본다."""
    try:
        import asyncio
        from sqlalchemy import select
        from app.db.models import Session as Room
        from app.db.session import async_session

        async def _q():
            async with async_session() as s:
                return {r for r in (await s.execute(select(Room.id))).scalars()}
        return asyncio.run(_q())
    except Exception:
        return None


def _blank(sid: str) -> dict:
    return {"session": sid, "mode": None, "roles": [], "tools": [], "files": [],
            "tasks": 0, "verify": None, "commit": None, "stall": 0.0,
            "questions": 0, "approvals": 0, "t0": None, "t1": None, "status": None}


def split_runs(events: list[dict]) -> list[dict]:
    """done 이벤트를 경계로 run을 복원한다. 세션은 오래 사는 방이라 session_id로는 못 나눈다."""
    cur: dict[str, dict] = {}
    prev_ts: dict[str, datetime.datetime] = {}
    runs: list[dict] = []
    for ev in events:
        sid = ev.get("session_id") or ""
        if sid in TEST_SESSIONS:
            continue
        r = cur.setdefault(sid, _blank(sid))
        d = ev.get("data") or {}
        t = ev.get("type")
        try:
            ts = datetime.datetime.fromisoformat(ev["ts"])
        except (KeyError, ValueError):
            continue
        if r["t0"] is None:
            r["t0"] = ts
        else:
            gap = (ts - prev_ts[sid]).total_seconds()
            r["stall"] = max(r["stall"], gap)
        prev_ts[sid] = ts

        if t == "agent_mode":
            r["mode"] = d.get("mode")
        elif t == "role_start":
            r["roles"].append(d.get("role") or "?")
            r["model"] = d.get("model") or r.get("model")
        elif t == "tool_call":
            r["tools"].append(d.get("name") or "?")
        elif t == "state_update":
            r["files"] = list(d.get("files_changed") or r["files"])
        elif t == "task_update":
            r["tasks"] = len(d.get("tasks") or [])
        elif t == "verify_start":
            r["verify"] = "실행"
        elif t == "verify_failed":
            r["verify"] = "실패"
            r["fail_report"] = str(d.get("report", ""))[:400]
        elif t == "verify_unavailable":
            r["verify"] = "불가"
        elif t == "autocommit":
            r["commit"] = d
        elif t == "question_request":
            r["questions"] += 1
        elif t == "approval_request":
            r["approvals"] += 1
        elif t == "done":
            r["status"] = d.get("status") or "?"
            r["t1"] = ts
            r["seconds"] = (ts - r["t0"]).total_seconds()
            runs.append(r)
            cur[sid] = _blank(sid)
    return runs


def flags(run: dict) -> list[str]:
    """프로세스 관점의 이상 징후. 모델이 무슨 말을 했는지는 보지 않는다."""
    out = []
    ok = run["status"] in ("completed", "completed_unverified")
    edits = len(run["files"])
    if run["status"] == "completed" and not edits and run["roles"] not in ([ "chat" ], []):
        out.append("변경0-완료")            # 아무것도 안 바꿨는데 성공으로 기록
    if run["commit"] and not edits:
        out.append("변경없이-커밋")          # 남의 변경을 쓸어담았을 가능성
    if edits and run["verify"] in (None, "불가"):
        out.append("검증없이-변경")          # 고쳤는데 test/build가 안 돌았다
    if edits >= MANY_FILES and not run["tasks"]:
        out.append("계획없이-다중파일")
    if run["stall"] >= STALL_SECONDS:
        out.append(f"대기{run['stall']:.0f}s")
    if run["status"] in ("verification_failed", "failed", "max_steps", "repeated",
                         "review_limit", "context_blocked"):
        out.append(run["status"])
    if not ok and run["status"] not in ("cancelled",) and not out:
        out.append(run["status"])
    return out


def report(runs: list[dict], only_flagged: bool, verbose: bool, limit: int) -> None:
    counts = collections.Counter()
    flagged = collections.Counter()
    for r in runs:                       # 집계는 전체로, 출력만 최근 것으로 자른다
        counts[r["status"]] += 1
        for x in flags(r):
            flagged[x.split("대기")[0] or "대기"] += 1
    view = [r for r in runs if flags(r)] if only_flagged else runs
    for r in view[-limit:]:
        f = flags(r)
        roles = "→".join(r["roles"]) or "-"
        tools = collections.Counter(r["tools"])
        tool_s = " ".join(f"{k}×{v}" for k, v in tools.most_common(4)) or "-"
        head = (f"{r['t1']:%m-%d %H:%M} {r['session'][:8]} [{r['mode'] or '-'}] "
                f"{r['status']} {r.get('seconds', 0):.0f}s")
        print(head + ("  ⚑ " + ", ".join(f) if f else ""))
        print(f"    역할 {roles} · 도구 {len(r['tools'])}({tool_s}) · 변경 {len(r['files'])}"
              f" · 태스크 {r['tasks']} · 검증 {r['verify'] or '-'}"
              + (f" · 커밋 {'push' if r['commit'].get('pushed') else 'local'}" if r["commit"] else ""))
        if verbose and r["files"]:
            print("    파일 " + ", ".join(r["files"][:8]))
        if verbose and r.get("fail_report"):
            print("    실패 " + r["fail_report"].replace("\n", " ")[:160])
    print(f"\nrun {len(runs)}건 · " + " ".join(f"{k}={v}" for k, v in counts.most_common()))
    if flagged:
        print("이상 징후 " + " ".join(f"{k}={v}" for k, v in flagged.most_common()))


def _self_test() -> None:
    def ev(sid, t, ts, **data):
        return {"session_id": sid, "ts": f"2026-08-23T10:{ts}", "type": t, "data": data}

    events = [
        ev("a", "agent_mode", "00:00", mode="single"),
        ev("a", "role_start", "00:01", role="developer", model="flash"),
        ev("a", "tool_call", "00:02", name="edit_file"),
        ev("a", "state_update", "00:03", files_changed=["x.py"]),
        ev("a", "verify_start", "00:04"),
        ev("a", "autocommit", "00:05", committed=True, pushed=True),
        ev("a", "done", "00:06", status="completed"),
        # 두 번째 run: 아무것도 안 바꿨는데 완료 + 커밋(과거의 사고 모양)
        ev("a", "role_start", "01:00", role="developer", model="flash"),
        ev("a", "tool_call", "01:01", name="grep"),
        ev("a", "autocommit", "05:00", committed=True, pushed=True),
        ev("a", "done", "05:01", status="completed"),
        ev("s1", "done", "06:00", status="completed"),   # 테스트 세션은 제외돼야 한다
    ]
    runs = split_runs(events)
    assert len(runs) == 2, runs
    assert runs[0]["status"] == "completed" and runs[0]["files"] == ["x.py"]
    assert flags(runs[0]) == [], flags(runs[0])
    f2 = flags(runs[1])
    assert "변경0-완료" in f2 and "변경없이-커밋" in f2, f2
    assert any(x.startswith("대기") for x in f2), f2      # 01:01 → 05:00 공백
    assert runs[1]["seconds"] == 241, runs[1]["seconds"]
    # 변경했는데 검증이 안 돈 run
    runs2 = split_runs([
        ev("b", "role_start", "00:00", role="developer"),
        ev("b", "state_update", "00:01", files_changed=["a.py", "b.py", "c.py"]),
        ev("b", "done", "00:02", status="completed_unverified"),
    ])
    assert "검증없이-변경" in flags(runs2[0]) and "계획없이-다중파일" in flags(runs2[0])
    print("review 파서·규칙 자체검증 통과 ✓")


def main() -> None:
    ap = argparse.ArgumentParser(description="에이전트 run 리뷰(읽기 전용)")
    ap.add_argument("--days", type=int, default=1, help="며칠치 로그(기본 1 = 오늘)")
    ap.add_argument("--session", default="", help="세션 id 접두사로 필터")
    ap.add_argument("--flags", action="store_true", help="이상 징후가 있는 run만")
    ap.add_argument("--verbose", action="store_true", help="파일·실패 리포트까지")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--all", action="store_true", help="삭제된 방(bench 등)의 run도 포함")
    ap.add_argument("--self-test", action="store_true", help="파서·규칙 검증(로그 불필요)")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return
    runs = split_runs(load_events(a.days))
    if not a.all:
        live = live_sessions()
        if live is not None:
            dropped = len(runs)
            runs = [r for r in runs if r["session"] in live]
            dropped -= len(runs)
            if dropped:
                print(f"(삭제된 방의 run {dropped}건 제외 — bench 등. 보려면 --all)\n")
    if a.session:
        runs = [r for r in runs if r["session"].startswith(a.session)]
    if not runs:
        print("run 없음")
        sys.exit(0)
    report(runs, a.flags, a.verbose, a.limit)


if __name__ == "__main__":
    main()
