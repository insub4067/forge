"""신뢰성 게이트 검증 — 완료 시 task 자동 done + autocommit 게이트.

하네스가 모델 대신 장부를 마감하는지 결정적으로 확인한다(LLM/네트워크 없음).
실행: python test_reliability_gates.py
"""
import asyncio

from app.runtime import agent as A


async def send_collector(events):
    async def send(event_type, data):
        events.append((event_type, data))
    return send


async def main():
    rt = A.AgentRuntime()

    # ── _finalize_tasks: 남은 todo/in_progress를 done으로, task_update emit ──
    stored = {"tasks": [
        {"title": "a", "status": "todo"},
        {"title": "b", "status": "in_progress"},
        {"title": "c", "status": "done"},
    ]}

    async def fake_list(sid):
        return [dict(t) for t in stored["tasks"]]

    async def fake_replace(sid, tasks):
        stored["tasks"] = tasks

    A.store.list_tasks = fake_list
    A.store.replace_tasks = fake_replace

    events = []
    await rt._finalize_tasks("s1", await send_collector(events))
    assert all(t["status"] == "done" for t in stored["tasks"]), stored
    assert any(e[0] == "task_update" for e in events), events
    print("finalize_tasks: OK — 남은 task 전부 done + task_update emit")

    # 이미 전부 done이면 재저장·이벤트 없음(불필요한 쓰기 방지)
    events2 = []
    await rt._finalize_tasks("s1", await send_collector(events2))
    assert not events2, events2
    print("finalize_tasks(변경 없음): OK — 재저장 안 함")

    # task 없으면 no-op
    stored["tasks"] = []
    events3 = []
    await rt._finalize_tasks("s1", await send_collector(events3))
    assert not events3, events3
    print("finalize_tasks(task 없음): OK")

    # ── _fail_pending_tasks: 비완료 종료 시 testing/working → blocked, done/todo 불변 ──
    stored["tasks"] = [
        {"title": "a", "status": "testing"},
        {"title": "b", "status": "working"},
        {"title": "c", "status": "done"},
        {"title": "d", "status": "todo"},
    ]
    events_f = []
    await rt._fail_pending_tasks("s1", await send_collector(events_f))
    _byt = {t["title"]: t["status"] for t in stored["tasks"]}
    assert _byt == {"a": "blocked", "b": "blocked", "c": "done", "d": "todo"}, stored
    assert any(e[0] == "task_update" for e in events_f), events_f
    print("fail_pending_tasks: OK — testing/working만 blocked, done/todo 불변")

    # 강등 대상 없으면 재저장·이벤트 없음(불필요한 쓰기 방지)
    events_f2 = []
    await rt._fail_pending_tasks("s1", await send_collector(events_f2))
    assert not events_f2, events_f2
    print("fail_pending_tasks(변경 없음): OK")

    # ── _autocommit 게이트 ──
    A.settings.auto_commit = True
    events4 = []
    await rt._autocommit("", "goal", await send_collector(events4))  # ws 없음 → no-op
    assert not events4, events4
    print("autocommit(ws 없음): OK — no-op")

    A.settings.auto_commit = False
    events5 = []
    await rt._autocommit("/tmp", "goal", await send_collector(events5))  # 끔 → no-op
    assert not events5, events5
    print("autocommit(AUTO_COMMIT=0): OK — no-op")
    A.settings.auto_commit = True  # 원복

    # ── _verify: 프로세스가 test/build를 실제로 돌려 신뢰성을 보장 ──
    import tempfile
    import os
    import json

    async def _ns(t, d):
        pass

    with tempfile.TemporaryDirectory() as d:  # 검증 대상 없음 → unavailable(성공으로 기록 안 함)
        st, _ = await rt._verify(d, _ns)
        assert st == "unavailable", st
    with tempfile.TemporaryDirectory() as d:  # 빌드 실패(node_modules 있음) → failed
        open(os.path.join(d, "package.json"), "w").write(
            json.dumps({"name": "t", "version": "1.0.0", "scripts": {"build": "exit 1"}}))
        os.mkdir(os.path.join(d, "node_modules"))
        st, rep = await rt._verify(d, _ns)
        assert st == "failed", (st, rep)
    with tempfile.TemporaryDirectory() as d:  # 빌드 성공 → passed
        open(os.path.join(d, "package.json"), "w").write(
            json.dumps({"name": "t", "version": "1.0.0", "scripts": {"build": "exit 0"}}))
        os.mkdir(os.path.join(d, "node_modules"))
        st, rep = await rt._verify(d, _ns)
        assert st == "passed", (st, rep)
    with tempfile.TemporaryDirectory() as d:  # node_modules 없음 → 실행불가 → unavailable(거짓 failed 방지)
        open(os.path.join(d, "package.json"), "w").write(
            json.dumps({"name": "t", "version": "1.0.0", "scripts": {"build": "exit 1"}}))
        st, _ = await rt._verify(d, _ns)
        assert st == "unavailable", st
    print("verify 3-state: OK — passed/failed/unavailable 구분, 거짓 failed 방지")

    # ── _verify pytest: exit code별 3상태 분리 ──
    # 가짜 .venv/bin/python — `import pytest` 결과와 `-m pytest` exit code를 제어.
    # exit 0=passed, 1=failed, 2(수집/설정 오류)=unavailable, 미설치=unavailable.
    with tempfile.TemporaryDirectory() as d:
        bd = os.path.join(d, "backend")
        os.makedirs(os.path.join(bd, ".venv", "bin"))
        with open(os.path.join(bd, "test_x.py"), "w") as f:
            f.write("def test_x():\n    pass\n")
        interp = os.path.join(bd, ".venv", "bin", "python")
        with open(interp, "w") as f:
            f.write("#!/usr/bin/env python3\n"
                    "import os, sys\n"
                    "if sys.argv[1:2] == ['-c']:\n"
                    "    sys.exit(0 if os.environ.get('FAKE_PYTEST_INSTALLED', '1') == '1' else 1)\n"
                    "sys.exit(int(os.environ.get('FAKE_PYTEST_EXIT', '0')))\n")
        os.chmod(interp, 0o755)

        def _set(**kw):
            for k in ("FAKE_PYTEST_INSTALLED", "FAKE_PYTEST_EXIT"):
                os.environ.pop(k, None)
            os.environ.update(kw)

        _set(FAKE_PYTEST_EXIT="0")  # exit 0 = 통과 → passed
        st, rep = await rt._verify(d, _ns)
        assert st == "passed", (st, rep)

        _set(FAKE_PYTEST_EXIT="1")  # exit 1 = 실제 실패 → failed
        st, rep = await rt._verify(d, _ns)
        assert st == "failed", (st, rep)

        _set(FAKE_PYTEST_EXIT="2")  # exit 2 = 수집/설정 오류 → unavailable(거짓 failed 방지)
        st, rep = await rt._verify(d, _ns)
        assert st == "unavailable", (st, rep)

        _set(FAKE_PYTEST_INSTALLED="0")  # pytest 미설치 → 실행 불가 → unavailable
        st, rep = await rt._verify(d, _ns)
        assert st == "unavailable", (st, rep)

        # 핵심 회귀: pytest 실행/설정 오류(exit 4/5) + 다른 check(build) 통과해도
        # 전체를 PASS로 오판하면 안 된다 — '검증 성공'으로 기록 금지(unavailable 유지).
        fd = os.path.join(d, "frontend")
        os.makedirs(os.path.join(fd, "node_modules"))
        with open(os.path.join(fd, "package.json"), "w") as f:
            f.write(json.dumps({"name": "t", "version": "1.0.0", "scripts": {"build": "exit 0"}}))

        _set(FAKE_PYTEST_EXIT="4")  # 설정/사용법 오류 + build 통과 → 전체 unavailable(거짓 passed 금지)
        st, rep = await rt._verify(d, _ns)
        assert st == "unavailable", (st, rep)
        assert "exit 4" in rep, rep

        _set(FAKE_PYTEST_EXIT="5")  # 테스트 수집 0 + build 통과 → unavailable
        st, rep = await rt._verify(d, _ns)
        assert st == "unavailable", (st, rep)
        assert "exit 5" in rep, rep

        _set(FAKE_PYTEST_EXIT="0")  # 전부 통과(pytest + build) → passed (오판 금지가 지나치지 않음)
        st, rep = await rt._verify(d, _ns)
        assert st == "passed", (st, rep)

        for k in ("FAKE_PYTEST_INSTALLED", "FAKE_PYTEST_EXIT"):
            os.environ.pop(k, None)
    print("verify pytest 3-state: OK — exit 0=passed / 1=failed / 2·미설치=unavailable, 설정오류+통과=PASS 오판 금지")

    # ── 승인 경계: auto_approve 세션만 자동 승인, 그 외는 approval_request ──
    from app.tools import registry as R

    async def _collector(events):
        async def send(evt_type, data):
            events.append((evt_type, data))
        return send

    # auto_approve 세션 → 자동 승인 + approval_auto 이벤트
    rt.set_auto_approve("s-aa", True)
    ev = []
    decision = await rt._request_approval("write_file", {"path": "/tmp/a"}, await _collector(ev), "s-aa")
    assert decision == "approve", decision
    assert any(t == "approval_auto" for t, _ in ev), ev
    assert not rt.pending_approvals, "자동 승인은 pending에 남지 않아야 함"
    print("승인 경계(auto_approve): OK — 자동 승인 + approval_auto, pending 없음")

    # auto_approve 아닌 세션 → approval_request 전송 + pending 등록(승인 대기)
    rt.set_auto_approve("s-manual", False)
    ev = []
    # _request_approval은 pending future를 await로 기다리므로 별도 task로 실행하고,
    # pending이 등록된 뒤 resolve_pending_approvals로 승인한다.
    task = asyncio.create_task(
        rt._request_approval("write_file", {"path": "/tmp/b"}, await _collector(ev), "s-manual"))
    await asyncio.sleep(0.05)  # pending 등록 대기
    assert any(t == "approval_request" for t, _ in ev), ev
    assert rt.pending_approvals, "수동 세션은 pending에 남아 승인을 기다려야 함"
    rt.resolve_pending_approvals("s-manual")
    decision = await task
    assert decision == "approve", decision
    print("승인 경계(수동): OK — approval_request 전송 + pending 등록 후 승인")

    # resolve_pending_approvals(session_id)는 해당 세션 pending만 승인(타 세션 무관)
    rt.set_auto_approve("s-other", False)
    fut_other = asyncio.get_running_loop().create_future()
    rt.pending_approvals["other-1"] = fut_other
    rt._pending_meta["other-1"] = {"session_id": "s-other", "kind": "approval"}
    fut_mine = asyncio.get_running_loop().create_future()
    rt.pending_approvals["mine-1"] = fut_mine
    rt._pending_meta["mine-1"] = {"session_id": "s-manual", "kind": "approval"}
    n = rt.resolve_pending_approvals("s-manual")
    assert n == 1, n
    assert fut_mine.done() and fut_mine.result() == "approve", "해당 세션 pending은 승인돼야 함"
    assert not fut_other.done(), "타 세션 pending은 승인되면 안 됨"
    rt.pending_approvals.pop("other-1", None)
    rt._pending_meta.pop("other-1", None)
    rt.pending_approvals.pop("mine-1", None)
    rt._pending_meta.pop("mine-1", None)
    print("resolve_pending_approvals(세션 필터): OK — 해당 세션만 승인, 타 세션 무관")

    # set_auto_approve(False) → 세션을 auto_approve 집합에서 제거(권한 축소)
    rt.set_auto_approve("s-aa", False)
    assert "s-aa" not in rt._auto_approve_sessions, "auto_approve 해제 시 집합에서 제거돼야 함"
    print("set_auto_approve(False): OK — auto_approve 집합에서 제거(권한 축소)")

    # BLOCKED_COMMANDS가 bash 실행 시 PermissionError로 차단
    for blocked in R.BLOCKED_COMMANDS:
        cmd = blocked.strip() + " something"
        try:
            await R.execute_tool("bash", {"command": cmd}, "/tmp")
            raise AssertionError(f"차단돼야 함: {cmd}")
        except PermissionError:
            pass
    print("BLOCKED_COMMANDS: OK — rm -rf/sudo/chmod 777/kill/uvicorn 전부 PermissionError 차단")

    # APPROVAL_REQUIRED 도구는 auto_approve 세션에서도 승인 게이트를 통과해야 실행됨
    # (자동 승인은 게이트 우회가 아니라 승인 결정만 자동화)
    assert "write_file" in R.APPROVAL_REQUIRED
    assert "bash" in R.APPROVAL_REQUIRED
    assert "build_frontend" in R.APPROVAL_REQUIRED
    print("APPROVAL_REQUIRED: OK — write_file/bash/build_frontend 포함")

    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
