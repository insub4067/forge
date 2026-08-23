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

    print("\n모든 케이스 통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
