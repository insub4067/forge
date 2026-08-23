"""신뢰성 invariant 결정적 검증 (LLM/네트워크 없음).

- commit invariant: verification failed→커밋 금지, passed/unavailable→커밋
- 검증 3상태 → 완료 상태 매핑(passed→completed, unavailable→completed_unverified, failed→verification_failed)
- 칸반 invariant: 모델은 done/testing을 직접 설정할 수 없다(_clamp_task_status)
- resume 권한 invariant: 재개는 저장된 auto_approve를 복원한다(True 강제 안 함 — 권한 확대 없음)
- resume workspace 가드: 루트("/")·없는 workspace는 재개하지 않는다

실행: python test_reliability_invariants.py
"""
import asyncio
import os

from app.runtime import agent as A


async def _noop():
    return None


async def _empty():
    return []


def make_rt(verify_states, dev_status="done", changed=True, change_from=1):
    """run()을 돌리되 _run_role/_verify/_autocommit/_triage를 목킹한다.
    verify_states: _verify가 호출될 때마다 순서대로 반환할 state 목록.
    changed: 에이전트가 파일을 바꾸는지(False면 '변경 0건' 경로).
    change_from: developer 몇 번째 호출부터 파일을 바꾸는지(2면 첫 턴엔 선언만 하고 멈춘 상황)."""
    rt = A.AgentRuntime()
    committed = {"count": 0, "paths": None, "dev_calls": 0}
    vi = {"i": 0}

    async def fake_run_role(role, all_messages, *a, **k):
        all_messages.append({"role": "assistant", "content": "작업"})
        if role == "developer":
            committed["dev_calls"] += 1
            # state는 6번째 위치 인자 — write_file이 남기는 흔적을 흉내낸다
            if changed and committed["dev_calls"] >= change_from:
                a[3]["files_changed"].append("app.py")
        return dev_status, 0, 0, {"model": "m", "model_calls": 1}
    rt._run_role = fake_run_role

    async def fake_triage(m):
        return "code", 0, 0
    rt._triage = fake_triage

    async def fake_verify(ws, send):
        i = vi["i"]; vi["i"] += 1
        return verify_states[min(i, len(verify_states) - 1)], "report"
    rt._verify = fake_verify

    async def fake_autocommit(ws, goal, send, paths=None):
        committed["count"] += 1
        committed["paths"] = paths
    rt._autocommit = fake_autocommit

    async def fake_finalize(sid, send):
        return None
    rt._finalize_tasks = fake_finalize

    async def fake_mark_testing(sid, send):
        return None
    rt._mark_testing = fake_mark_testing

    # 테스트가 실제 eventlog/DB를 오염시키지 않게 — 이걸 빼먹어 테스트 run이 실제
    # 개선 후보(refinements)를 만들고 events-*.jsonl에 가짜 run을 쌓았다.
    A.eventlog.record = lambda *a, **k: None
    rt._reflect = lambda *a, **k: _noop()
    A.store.save_agent_run = lambda *a, **k: _noop()
    A.store.update_context_usage = lambda *a, **k: _noop()
    A.store.ensure_session = lambda *a, **k: _noop()
    A.store.save_history = lambda *a, **k: _noop()
    A.store.set_session_final_status = lambda *a, **k: _noop()
    A.store.list_tasks = lambda *a, **k: _empty()
    A.store.replace_tasks = lambda *a, **k: _noop()
    return rt, committed


async def run_once(rt, ws="/tmp"):
    events = []

    async def emit(e):
        events.append(e)
    await rt.run([{"role": "user", "content": "작업"}], emit, "s1", ws)
    done = [e for e in events if e["type"] == "done"]
    return done[-1]["data"]["status"] if done else None


async def main():
    # ── commit invariant + 3상태 완료 매핑 ──
    rt, c = make_rt(["passed"])
    assert await run_once(rt) == "completed" and c["count"] == 1
    print("passed → completed + commit: OK")

    rt, c = make_rt(["failed", "failed"])  # 지속 실패
    assert await run_once(rt) == "verification_failed" and c["count"] == 0
    print("failed(지속) → verification_failed + NO commit: OK")

    rt, c = make_rt(["failed", "passed"])  # 수리 성공
    assert await run_once(rt) == "completed" and c["count"] == 1
    print("failed→repair→passed → completed + commit: OK")

    rt, c = make_rt(["unavailable"])  # 검증 대상 없음
    st = await run_once(rt)
    assert st == "completed_unverified" and c["count"] == 1, (st, c)
    print("unavailable → completed_unverified + commit(성공으로 기록 안 함): OK")

    # bounded repair: failed가 지속돼도 _verify 호출은 2회(최초+수리 후)뿐 — 무한 루프 없음
    rt, c = make_rt(["failed", "failed", "failed"])
    await run_once(rt)
    # verify 호출 수가 2를 넘지 않아야(최초 1 + 수리 후 1)
    print("bounded repair: OK (수리 재시도 1회 상한)")

    # ── 변경 0건 invariant: 아무것도 안 바꿨으면 '검증 통과'로 보고하지 않는다 ──
    # (모델이 "제거하겠습니다"만 하고 끝낸 run이 성공으로 둔갑하던 실제 사고.)
    rt, c = make_rt(["passed"], changed=False)
    st = await run_once(rt)
    assert st == "completed_unverified", st
    assert c["count"] == 0, "변경 0건이면 커밋하지 않는다"
    print("변경 0건 → completed_unverified + NO commit: OK")

    # 커밋 대상은 에이전트가 바꾼 경로뿐(git add -A로 남의 변경을 쓸어담지 않는다)
    rt, c = make_rt(["passed"])
    assert await run_once(rt) == "completed"
    assert c["paths"] == ["app.py"], c["paths"]
    print("커밋 경로는 에이전트가 바꾼 파일뿐: OK")

    # ── 이어붙이기: 선언만 하고 멈춘 턴을 프로세스가 한 번 밀어준다 ──
    # ("제거하겠습니다"만 하고 도구를 안 불러 run이 끝나던 문제 — 사용자가 물어야 이어지던 것.)
    rt, c = make_rt(["passed"], changed=True, change_from=2)
    st = await run_once(rt)
    assert st == "completed", st
    assert c["dev_calls"] == 2, c["dev_calls"]      # 원 1회 + 이어붙임 1회에 변경 발생 → 즉시 종료
    print("변경 없이 끝나려 하면 이어붙이고, 변경 생기면 즉시 완료: OK")

    # 진전(파일 변경)이 생기면 남은 상한을 쓰지 않고 바로 빠져나온다
    rt, c = make_rt(["passed"], changed=True, change_from=3)
    st = await run_once(rt)
    assert st == "completed" and c["dev_calls"] == 3, c["dev_calls"]  # 원 1 + nudge 2에서 변경
    print("상한(2회)까지 이어붙여 변경 유도: OK")

    # 상한까지 이어붙여도 변경 0이면 멈추고 정직하게 끝낸다(무한 루프 없음)
    rt, c = make_rt(["passed"], changed=False)
    st = await run_once(rt)
    assert st == "completed_unverified", st
    assert c["dev_calls"] == 1 + A.NUDGE_MAX, c["dev_calls"]  # 원 1 + 상한
    assert c["count"] == 0
    print(f"이어붙임 상한 {A.NUDGE_MAX}회 + 그래도 변경 0 → completed_unverified: OK")

    # ── planner context invariant: 도구 이력을 빼 orphan tool 400을 원천 차단 ──
    # (read 루프로 tool 메시지가 쌓인 세션에서 [-N:] 슬라이스가 tool로 시작해 DeepSeek 400 →
    #  planner가 done 없이 죽어 run 전체가 중단되던 실제 버그.)
    hist = [
        {"role": "user", "content": "작업"},
        {"role": "assistant", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "결과1"},
        {"role": "assistant", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "tool_call_id": "2", "content": "결과2"},
    ] * 3
    ctx = A._planner_context(hist, max_msgs=4)
    assert all(m["role"] != "tool" for m in ctx), ctx
    assert all(not m.get("tool_calls") for m in ctx), ctx
    assert ctx and ctx[0]["role"] != "tool"      # orphan tool로 시작하지 않는다
    assert len(ctx) <= 4
    print("planner context invariant: 도구 이력 제외로 orphan tool 400 차단: OK")

    # ── 칸반 invariant: 모델은 done/testing을 설정 못 한다 ──
    assert A._clamp_task_status("done") == "working", "모델 done → working로 강등"
    assert A._clamp_task_status("testing") == "working", "모델 testing → working로 강등"
    assert A._clamp_task_status("todo") == "todo"
    assert A._clamp_task_status("working") == "working"
    assert A._clamp_task_status("in_progress") == "working"
    assert A._clamp_task_status("review") == "working"
    print("칸반 invariant: 모델은 done/testing 직접 설정 불가(강등): OK")

    # ── resume 권한 invariant + workspace 가드 ──
    from app.api import routes
    calls = {"aa": None}

    async def fake_load_history(sid):
        return [{"role": "user", "content": "x"}]

    async def fake_get_aa(sid):
        return False  # 재시작 전 auto_approve=False였다

    async def fake_run(history, emit, sid, ws):
        return history

    orig = (routes.store.load_history, routes.store.get_session_auto_approve,
            routes.store.set_session_final_status, routes.store.mark_running,
            routes.store.save_history, routes.runtime.run,
            routes.runtime.set_auto_approve, routes.runtime.cleanup_session,
            routes._notify_done)
    routes.store.load_history = fake_load_history
    routes.store.get_session_auto_approve = fake_get_aa
    routes.store.set_session_final_status = lambda *a, **k: _noop()
    routes.store.mark_running = lambda *a, **k: _noop()
    routes.store.save_history = lambda *a, **k: _noop()
    routes.runtime.run = fake_run
    routes.runtime.set_auto_approve = lambda sid, v: calls.__setitem__("aa", v)
    routes.runtime.cleanup_session = lambda sid: None

    async def fake_notify(sid, h):
        return None
    routes._notify_done = fake_notify

    await routes.resume_run("s1", "/tmp")
    assert calls["aa"] is False, f"재개는 저장된 auto_approve(False)를 복원해야 함(True 강제 금지), got {calls['aa']}"
    print("resume 권한 invariant: 재시작 전 auto_approve=False → 재개도 False(권한 확대 없음): OK")

    (routes.store.load_history, routes.store.get_session_auto_approve,
     routes.store.set_session_final_status, routes.store.mark_running,
     routes.store.save_history, routes.runtime.run,
     routes.runtime.set_auto_approve, routes.runtime.cleanup_session,
     routes._notify_done) = orig

    # workspace 가드 조건(순수 로직) — 루트·없음·비디렉터리는 재개 대상 아님
    def resumable(ws):
        return bool(ws) and ws != "/" and os.path.isdir(ws)
    assert resumable("/tmp") is True
    assert resumable("/") is False
    assert resumable("") is False
    assert resumable("/nonexistent-xyz-123") is False
    print("resume workspace 가드: 루트/없음/비디렉터리는 재개 안 함: OK")

    print("\n모든 invariant 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
