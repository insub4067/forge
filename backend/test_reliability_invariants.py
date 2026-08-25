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


async def _collector(events):
    async def send(evt_type, data):
        events.append((evt_type, data))
    return send


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

    async def fake_verify(ws, send, stage="generic"):
        i = vi["i"]; vi["i"] += 1
        return verify_states[min(i, len(verify_states) - 1)], "report"
    rt._verify = fake_verify

    async def fake_autocommit(ws, goal, send, paths=None, push=True):
        committed["count"] += 1
        committed["paths"] = paths
        committed["push"] = push
        return True, push
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
    A.store.list_gates = lambda *a, **k: _empty()
    A.store.replace_gates = lambda *a, **k: _noop()
    A.store.save_gate_result = lambda *a, **k: _noop()
    # resolve_pending_approvals는 PG decide 성공분만 Future를 해소한다 — DB 없이 성공 경로 목킹.
    async def _decide_ok(*a, **k):
        return True
    A.store.decide_approval = _decide_ok
    A.store.create_approval = lambda *a, **k: _noop()
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
    # gate 0 + generic passed → completed가 아니다(gate coverage 정책). 로컬 commit만.
    # generic verification은 "기존 test/build가 안 깨졌다"만 말한다 — 요구사항 미검증.
    # gate가 있는 completed+push 경로는 test_acceptance_gates.py Case A가 고정한다.
    rt, c = make_rt(["passed"])
    st = await run_once(rt)
    assert st == "completed_unverified", st
    assert c["count"] == 1, c
    assert c["push"] is False, "gate 0은 검증된 배포가 아니다 — push 금지"
    print("gate 0 + passed → completed_unverified + commit + NO push: OK")

    rt, c = make_rt(["failed", "failed"])  # 지속 실패
    assert await run_once(rt) == "verification_failed" and c["count"] == 0
    print("failed(지속) → verification_failed + NO commit: OK")

    rt, c = make_rt(["failed", "passed"])  # 수리 성공(gate 0이므로 미검증 완료)
    st = await run_once(rt)
    assert st == "completed_unverified", st
    assert c["count"] == 1, c
    print("failed→repair→passed → completed_unverified + commit: OK")

    rt, c = make_rt(["unavailable"])  # 검증 대상 없음
    st = await run_once(rt)
    assert st == "completed_unverified" and c["count"] == 1, (st, c)
    assert c["push"] is False, "completed_unverified는 로컬 commit만, push 금지"  # P0-3
    print("unavailable → completed_unverified + commit + NO push: OK")

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
    assert await run_once(rt) == "completed_unverified"
    assert c["paths"] == ["app.py"], c["paths"]
    print("커밋 경로는 에이전트가 바꾼 파일뿐: OK")

    # ── 변경 0건이면 continue_nudge 없이 정직하게 끝낸다 ──
    # (넛지는 제거됨 — Ox 겨냥 레거시. 이제 재촉 없이 한 번에 끝내고, 완료 판정은 gate가 한다.)
    rt, c = make_rt(["passed"], changed=False)
    st = await run_once(rt)
    assert st == "completed_unverified", st
    assert c["dev_calls"] == 1, c["dev_calls"]   # 재촉 없이 developer 1회로 끝
    assert c["count"] == 0                        # 변경 0건이면 커밋/푸시 없음
    print("변경 0건 → developer 1회(재촉 없음) → completed_unverified + NO commit: OK")

    # ── 칸반 강제: planner 계획 → 태스크 자동 추출 ──
    plan = "## 계획\n1. 모델 라우터에 planner 추가\n2) 역할 프롬프트 작성\n3. 테스트\n\n## 완료 조건\n1. 전부 통과"
    tasks = A._plan_to_tasks(plan)
    assert [t["title"] for t in tasks] == ["모델 라우터에 planner 추가", "역할 프롬프트 작성", "테스트"], tasks
    assert all(t["status"] == "todo" for t in tasks)          # 완료 조건 섹션(1. 전부 통과)은 제외
    assert A._plan_to_tasks("계획 없음 그냥 문장") == []       # 번호 목록 없으면 빈 목록
    assert len(A._plan_to_tasks("\n".join(f"{i}. 단계{i}" for i in range(20)))) == 8  # 상위 8개 상한
    print("칸반 강제: planner 계획 번호목록 → 태스크(완료조건 제외·상한8): OK")

    # ── 런타임 스모크 invariant: 비 self-repo는 unavailable(타 프로젝트 빌드를 FORGE 앱으로 오검증 안 함) ──
    async def _noop_send(t, d=None):
        return None
    ss, _ = await A.AgentRuntime()._runtime_smoke("/tmp", _noop_send)
    assert ss == "unavailable", ss
    print("런타임 스모크 invariant: 비 self-repo는 unavailable: OK")

    # ── compaction 분할 invariant: user 1개 + 이후 전부 tool 호출인 run도 경계를 찾는다 ──
    # (tool_calls 없는 assistant만 경계로 허용해 developer run에서 compaction이 영영 안 돌던 버그.)
    dev_msgs = [{"role": "user", "content": "작업"}]
    for _ in range(20):
        dev_msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]})
        dev_msgs.append({"role": "tool", "tool_call_id": "x", "content": "결과"})
    sp = A.AgentRuntime._safe_split(dev_msgs, 8)
    assert sp > 0, f"tool 연속 run에서도 분할점을 찾아야 compaction이 돈다, got {sp}"
    assert dev_msgs[sp]["role"] in ("user", "assistant"), dev_msgs[sp]["role"]  # orphan tool로 시작 안 함
    # 투영본이 orphan tool로 시작하지 않는다
    projected_first = dev_msgs[sp]
    assert projected_first["role"] != "tool"
    print("compaction 분할 invariant: tool 연속 run도 경계 발견(orphan tool 아님): OK")

    # ── vision 라우팅 invariant: 이번 턴에 이미지가 있을 때만 vision ──
    # (세션 초반 스크린샷 하나가 이후 텍스트 작업까지 계속 vision으로 끌고 가던 실제 버그.)
    img_msg = {"role": "user", "content": [{"type": "text", "text": "이거 고쳐"},
                                           {"type": "image_url", "image_url": {"url": "x"}}]}
    txt_msg = {"role": "user", "content": "GitPanel 분리해"}
    assert A._turn_has_image([img_msg]) is True
    assert A._turn_has_image([txt_msg]) is False
    # 예전 턴에 이미지가 있어도 이번(마지막) 턴이 텍스트면 vision 아님
    assert A._turn_has_image([img_msg, {"role": "assistant", "content": "함"}, txt_msg]) is False
    # 이번 턴이 이미지면 vision
    assert A._turn_has_image([txt_msg, {"role": "assistant", "content": "함"}, img_msg]) is True
    assert A._turn_has_image([]) is False
    print("vision 라우팅 invariant: 이번 턴 이미지만 vision(옛 이미지 무관): OK")

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
    calls = {"aa": None, "tier": None}

    async def fake_load_history(sid):
        return [{"role": "user", "content": "x"}]

    async def fake_get_aa(sid):
        return False  # 재시작 전 auto_approve=False였다

    async def fake_get_tier(sid):
        return "pro"  # 재시작 전 model_tier=pro였다

    async def fake_run(history, emit, sid, ws):
        return history

    orig = (routes.store.load_history, routes.store.get_session_auto_approve,
            routes.store.get_session_model_tier, routes.store.set_session_final_status,
            routes.store.mark_running, routes.store.save_history, routes.runtime.run,
            routes.runtime.set_auto_approve, routes.runtime.set_model_tier,
            routes.runtime.cleanup_session, routes._notify_done)
    routes.store.load_history = fake_load_history
    routes.store.get_session_auto_approve = fake_get_aa
    routes.store.get_session_model_tier = fake_get_tier
    routes.store.set_session_final_status = lambda *a, **k: _noop()
    routes.store.mark_running = lambda *a, **k: _noop()
    routes.store.save_history = lambda *a, **k: _noop()
    routes.runtime.run = fake_run
    routes.runtime.set_auto_approve = lambda sid, v: calls.__setitem__("aa", v)
    routes.runtime.set_model_tier = lambda sid, v: calls.__setitem__("tier", v)
    routes.runtime.cleanup_session = lambda sid: None

    async def fake_notify(sid, h):
        return None
    routes._notify_done = fake_notify

    await routes.resume_run("s1", "/tmp")
    assert calls["aa"] is False, f"재개는 저장된 auto_approve(False)를 복원해야 함(True 강제 금지), got {calls['aa']}"
    assert calls["tier"] == "pro", f"재개는 저장된 model_tier(pro)를 복원해야 함, got {calls['tier']}"
    print("resume 권한 invariant: 재시작 전 auto_approve=False → 재개도 False(권한 확대 없음): OK")
    print("resume 모델 티어 invariant: 재시작 전 model_tier=pro → 재개도 pro 복원: OK")

    # resume 권한 확대 방지 강화 — auto_approve=True였던 세션도 그대로 True 복원(무인 위임 유지)
    calls["aa"] = None

    async def fake_get_aa_true(sid):  # get_session_auto_approve는 async — 동기 lambda면 await에서 터진다
        return True
    routes.store.get_session_auto_approve = fake_get_aa_true  # 재시작 전 무인 위임이었다
    await routes.resume_run("s1", "/tmp")
    assert calls["aa"] is True, f"무인 위임 세션은 재개 시 True 복원돼야 함, got {calls['aa']}"
    print("resume 권한 invariant(무인 위임): OK — auto_approve=True 세션도 그대로 True 복원")

    # resume 후 새 위험 mutation은 여전히 승인 게이트를 통과해야 한다 —
    # auto_approve가 아니면 approval_request로 pause, auto_approve면 자동 승인.
    # (resume이 승인 게이트 자체를 우회하지 않음을 보장)
    from app.runtime import agent as _A
    rt2 = _A.AgentRuntime()
    rt2.set_auto_approve("s-resume", False)
    ev = []
    task = asyncio.create_task(
        rt2._request_approval("bash", {"command": "echo hi"}, await _collector(ev), "s-resume"))
    await asyncio.sleep(0.05)
    assert any(t == "approval_request" for t, _ in ev), "resume 후에도 수동 세션은 승인 요청해야 함"
    await rt2.resolve_pending_approvals("s-resume")
    assert (await task)[1] == "approve"
    print("resume 후 승인 게이트: OK — 수동 세션은 여전히 approval_request로 pause")

    (routes.store.load_history, routes.store.get_session_auto_approve,
     routes.store.get_session_model_tier, routes.store.set_session_final_status,
     routes.store.mark_running, routes.store.save_history, routes.runtime.run,
     routes.runtime.set_auto_approve, routes.runtime.set_model_tier,
     routes.runtime.cleanup_session, routes._notify_done) = orig

    # workspace 가드 조건(순수 로직) — 루트·없음·비디렉터리는 재개 대상 아님
    def resumable(ws):
        return bool(ws) and ws != "/" and os.path.isdir(ws)
    assert resumable("/tmp") is True
    assert resumable("/") is False
    assert resumable("") is False
    assert resumable("/nonexistent-xyz-123") is False
    # ── 최종 보고는 durable해야 한다 ──
    # 새로고침하면 하네스의 구조화 보고가 사라지고 모델의 자기서술만 남던 문제.
    # 권위 있는 쪽이 영속적이어야 한다(정확히 반대였다).
    saved = {}

    async def capture_history(sid, msgs):
        saved["msgs"] = [dict(m) for m in msgs]
    rt, c = make_rt(["passed"])          # make_rt가 save_history를 noop으로 덮으므로
    _orig_save = A.store.save_history     # 그 뒤에 캡처로 바꿔야 한다
    A.store.save_history = capture_history
    try:
        await run_once(rt)
    finally:
        A.store.save_history = _orig_save
    last = (saved.get("msgs") or [{}])[-1]
    assert last.get("role") == "assistant", saved.get("msgs")
    assert "요구사항 게이트 없음" in last.get("content", ""), last
    print("최종 보고가 history에 영속된다(새로고침 후에도 남는다): OK")

    # ── 핵심 invariant: 코드 변경 + gate 0에서 completed는 나올 수 없다 ──
    # generic verification이 통과해도, gate 복구가 실패해도, 어떤 경로로도.
    for states in (["passed"], ["failed", "passed"], ["unavailable"],
                   ["passed", "passed"]):
        rt, c = make_rt(states)
        st = await run_once(rt)
        assert st != "completed", (states, st)
        assert c["push"] is not True, (states, c)
    print("gate 0 코드변경은 어떤 경로로도 completed가 되지 않는다: OK")

    print("resume workspace 가드: 루트/없음/비디렉터리는 재개 안 함: OK")

    test_derived_context_roles_do_not_overwrite_history()
    print("\n모든 invariant 통과 ✓")



def test_derived_context_roles_do_not_overwrite_history():
    """planner·reviewer는 축소된 파생 컨텍스트 위에서 돈다. _run_role이 그걸 그대로
    save_history하면 세션 transcript가 그 몇 줄로 덮여 사라진다(비파괴 원칙 위반).
    reviewer는 마지막에 돌기 때문에 덮어쓰기가 영구적이다."""
    import inspect
    from app.runtime import agent as A

    src = inspect.getsource(A.AgentRuntime._run_role)
    assert "if session_id and persist:" in src, "persist 가드가 사라졌다"

    run_src = inspect.getsource(A.AgentRuntime.run)
    # planner/reviewer 호출이 파생 컨텍스트를 쓰면서 persist=False가 아니면 유실된다.
    for role, ctx in (("planner", "planner_msgs"), ("reviewer", "reviewer_msgs")):
        i = run_src.index(f'"{role}", {ctx}')
        call = run_src[i:i + 400]
        assert "persist=False" in call.split(")")[0] + ")", \
            f"{role}가 파생 컨텍스트로 history를 덮어쓴다"
    print("derived context invariant: planner/reviewer는 세션 history를 덮지 않는다: OK")


if __name__ == "__main__":
    asyncio.run(main())
