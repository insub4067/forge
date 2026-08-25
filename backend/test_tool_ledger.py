"""side-effect 실행 장부 — resume이 '실행됐는지 모르는' 부작용을 자동 재실행하지 않는다.

즉시 save가 재실행 창을 거의 닫았지만, 도구 실행 완료와 history 저장 사이의 극소 구간이
남는다. 그 구간에서 죽으면 history에는 흔적이 없고 부작용만 남는다. 장부는 실행 **전에**
started를 적어 그 구간을 관측 가능하게 만든다.

실제 DB·실제 도구 실행 경로로 검증한다(순수 함수만 테스트하면 배선 회귀를 못 잡는다).
subprocess로 격리 — 모듈 전역 async engine의 이벤트 루프 얽힘 회피(test_approvals와 동일).
실행: cd backend && .venv/bin/python -m pytest test_tool_ledger.py -q
"""
import os
import pathlib
import subprocess
import sys

_BACKEND = pathlib.Path(__file__).resolve().parent

_CODE = '''
import asyncio, json, os, tempfile, uuid
from sqlalchemy import select, update
from app.runtime.agent import AgentRuntime
from app.db import store
from app.db.session import engine, async_session
from app.db.models import Base, ToolLedger

class FakeAdapter:
    requires_reasoning_replay = False
    def __init__(self, path, content):
        self.n = 0; self.path = path; self.content = content
    async def stream_chat(self, messages, tools=None, thinking=False, reasoning_effort=None):
        self.n += 1
        if self.n == 1:
            yield {"tool_calls": [{"index": 0, "id": "call1", "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": self.path, "content": self.content})}}]}
        else:
            yield {"content": "완료했습니다."}

async def _rows(sid):
    async with async_session() as s:
        r = await s.execute(select(ToolLedger).where(ToolLedger.session_id == sid))
        return [(t.tool_name, t.status, t.run_id) for t in r.scalars()]

async def _run_once(rt, sid, ws, events, run_id):
    rt._run_ids[sid] = run_id
    fake = FakeAdapter("out.txt", "V1")
    rt._adapter_for = lambda m: fake
    async def send(t, d): events.append((t, d))
    state = {"files_changed": [], "errors": []}
    await rt._run_role("developer", [{"role": "user", "content": "파일 써"}],
                       send, sid, ws, state, [], 0)

async def _scenario():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ws = tempfile.mkdtemp()
    sid = "t-ledger-" + uuid.uuid4().hex[:8]
    await store.ensure_session(sid, "ledger", ws)
    path = os.path.join(ws, "out.txt")
    try:
        rt = AgentRuntime()
        rt._auto_approve_sessions.add(sid)   # 무인 경로(= resume이 도는 그 경로)

        # 1) 정상 실행 — 파일이 써지고 장부가 completed로 닫힌다.
        ev1 = []
        await _run_once(rt, sid, ws, ev1, "run-A")
        assert os.path.isfile(path) and open(path).read() == "V1", "정상 실행에서 파일 미작성"
        rows = await _rows(sid)
        assert rows == [("write_file", "completed", "run-A")], rows

        # 2) crash 시뮬레이션 — 저장 전에 죽어 started로 남은 상태를 만든다.
        async with async_session() as s:
            await s.execute(update(ToolLedger).where(ToolLedger.session_id == sid)
                            .values(status="started", completed_at=None))
            await s.commit()
        os.remove(path)   # 실제 반영 여부를 파일 존재로 관측하기 위해 지운다

        # 3) 다른 run이 같은 (tool, args)를 다시 실행하려 하면 차단된다.
        ev2 = []
        await _run_once(rt, sid, ws, ev2, "run-B")
        blocked = [d for t, d in ev2 if t == "tool_result" and "재실행 차단" in d.get("result", "")]
        assert blocked, [d for t, d in ev2 if t == "tool_result"]
        assert not os.path.exists(path), "차단됐는데 파일이 다시 써졌다(자동 재실행 발생)"
        # 차단은 새 장부 행을 만들지 않고(실행하지 않았으므로), 알린 행은 닫는다(1회 경고).
        assert await _rows(sid) == [("write_file", "reported", "run-A")], await _rows(sid)

        # 4) 경고 뒤에는 같은 호출이 진행된다 — 영구 차단이 아니라 자동 재실행 금지다.
        ev3 = []
        await _run_once(rt, sid, ws, ev3, "run-B")
        assert os.path.isfile(path), "1회 경고 뒤에도 계속 막혔다(영구 차단)"
        assert ("write_file", "completed", "run-B") in await _rows(sid), await _rows(sid)
        print("TOOL_LEDGER_OK")
    finally:
        await store.delete_room(sid)

asyncio.run(_scenario())
'''


def test_ambiguous_side_effect_is_not_auto_reexecuted():
    """started로만 남은 부작용은 자동 재실행하지 않는다(실제 DB·실제 write_file 경로)."""
    r = subprocess.run([sys.executable, "-c", _CODE], cwd=str(_BACKEND),
                       env=dict(os.environ), capture_output=True, text=True)
    assert "TOOL_LEDGER_OK" in r.stdout, f"stdout={r.stdout}\nstderr={r.stderr[-2000:]}"
    # 정리(delete_room)까지 통과해야 한다 — ToolLedger가 sessions FK를 잡아 방 삭제가
    # FK 위반으로 죽는 회귀를 여기서 잡는다(실제로 한 번 났다).
    assert r.returncode == 0, f"stderr={r.stderr[-2000:]}"
