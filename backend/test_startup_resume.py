"""startup resume는 한 세션 재개 실패로 나머지를 유실하지 않는다 (실측·LLM 없음).

실제 사고 모양: 재시작 후 중단 run을 순차 재개하던 fire-and-forget task에서
첫 세션의 resume이 예외를 던지면, 루프가 거기서 끊겨 나머지 세션이 영영 재개되지
않고 예외는 stderr로만 새어 조용히 사라진다(수동 재시작 배포에선 세션 유실).

실행: python test_startup_resume.py  (pytest로도 수집된다)
"""
import asyncio
import tempfile

from app import main as M
from app import errors as error_log
from app.db import store


def _run(items, resume_fn, monkeypatch):
    resumed, recorded, notes = [], [], []

    async def fake_note(sid):
        notes.append(sid)

    monkeypatch.setattr(store, "mark_interrupted_note", fake_note)
    monkeypatch.setattr(error_log, "record",
                        lambda src, msg, sid="": recorded.append((src, sid, msg)))
    asyncio.run(M._resume_interrupted_runs(items, resume_fn))
    return resumed, recorded, notes


def test_one_failure_does_not_strand_rest(monkeypatch):
    ws = tempfile.mkdtemp(prefix="forge-resume-")
    resumed = []

    async def resume_fn(rid, w):
        if rid == "bad":
            raise RuntimeError("boom")
        resumed.append(rid)

    _, recorded, _ = _run([
        {"id": "a", "workspace_path": ws, "final_status": "interrupted"},
        {"id": "bad", "workspace_path": ws, "final_status": "interrupted"},
        {"id": "c", "workspace_path": ws, "final_status": "interrupted"},
    ], resume_fn, monkeypatch)

    # 실패(bad) 뒤에도 c가 재개된다 — 한 건 실패가 나머지를 막지 않는다.
    assert resumed == ["a", "c"], resumed
    # 실패는 세션 id와 함께 error_log에 남는다(조용히 사라지지 않는다 = 가시성).
    assert any(sid == "bad" and src == "startup_resume" for src, sid, _ in recorded), recorded


def test_invalid_workspace_is_noted_not_resumed(monkeypatch):
    called = []

    async def resume_fn(rid, w):
        called.append(rid)

    _, _, notes = _run([
        {"id": "gone", "workspace_path": "/nonexistent/x", "final_status": "interrupted"},
        {"id": "root", "workspace_path": "/", "final_status": "interrupted"},
        {"id": "resuming", "workspace_path": tempfile.mkdtemp(), "final_status": "resuming"},
    ], resume_fn, monkeypatch)

    assert called == [], called                 # 재개 금지 대상은 resume_fn을 부르지 않는다
    assert set(notes) == {"gone", "root", "resuming"}, notes  # 대신 note로 남긴다


if __name__ == "__main__":
    class _MP:
        def __init__(self): self._undo = []
        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)
        def undo(self):
            for obj, name, old in reversed(self._undo): setattr(obj, name, old)

    for fn in (test_one_failure_does_not_strand_rest, test_invalid_workspace_is_noted_not_resumed):
        mp = _MP()
        try:
            fn(mp)
            print(f"{fn.__name__}: OK")
        finally:
            mp.undo()
    print("\nstartup resume 가시성 통과 ✓")
