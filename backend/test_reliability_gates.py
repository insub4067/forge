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

        for k in ("FAKE_PYTEST_INSTALLED", "FAKE_PYTEST_EXIT"):
            os.environ.pop(k, None)
    print("verify pytest 3-state: OK — exit 0=passed / 1=failed / 2·미설치=unavailable")

    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
