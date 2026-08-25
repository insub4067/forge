"""Durable Approval 상태기계 순수 로직 검증(DB 비의존). 보안 불변식을 결정적으로 고정한다.
실행: cd backend && .venv/bin/python -m pytest test_approvals.py -q
"""
from app.runtime import approvals as A


def test_args_hash_normalizes_and_detects_tampering():
    # 키 순서·공백이 달라도 같은 args면 같은 hash
    h1 = A.args_hash({"path": "a.py", "content": "x"})
    h2 = A.args_hash({"content": "x", "path": "a.py"})
    assert h1 == h2
    # 내용이 바뀌면 hash가 달라진다(변조 탐지)
    assert A.args_hash({"path": "a.py", "content": "y"}) != h1
    # 비직렬화 입력에도 예외 없이 결정적 문자열
    assert isinstance(A.args_hash({"x": {1, 2}}), str)
    print("OK args_hash 정규화·변조 탐지")


def test_can_decide_is_idempotent():
    # requested만 결정 가능 — 이미 결정된 것을 다시 결정할 수 없다(멱등)
    assert A.can_decide("requested") is True
    for s in ("approved", "rejected", "expired", "cancelled", "consumed"):
        assert A.can_decide(s) is False, s
    print("OK can_decide는 requested에서만(멱등)")


def _appr(**kw):
    base = {"session_id": "s1", "status": "approved",
            "args_hash": A.args_hash({"cmd": "ls"}), "expires_at_ts": 1000.0}
    base.update(kw)
    return base


def test_can_consume_enforces_all_invariants():
    good_hash = A.args_hash({"cmd": "ls"})
    # 정상: approved + 같은 session + hash 일치 + 미만료
    ok, why = A.can_consume(_appr(), "s1", good_hash, now_ts=500.0)
    assert ok and why == "ok"
    # 다른 session 차단
    ok, why = A.can_consume(_appr(), "other", good_hash, 500.0)
    assert not ok and why == "session_mismatch"
    # approved 아님(requested/rejected/consumed) 차단
    for st in ("requested", "rejected", "consumed", "expired", "cancelled"):
        ok, why = A.can_consume(_appr(status=st), "s1", good_hash, 500.0)
        assert not ok, st
    # 만료 차단
    ok, why = A.can_consume(_appr(), "s1", good_hash, now_ts=1500.0)
    assert not ok and why == "expired"
    # args 변조 차단
    ok, why = A.can_consume(_appr(), "s1", A.args_hash({"cmd": "rm -rf /"}), 500.0)
    assert not ok and why == "args_changed"
    print("OK can_consume: session·status·만료·args 변조 불변식")


def test_is_expired_only_for_pending():
    # requested가 만료시각을 넘기면 expired 후보
    assert A.is_expired({"status": "requested", "expires_at_ts": 100.0}, now_ts=200.0) is True
    assert A.is_expired({"status": "requested", "expires_at_ts": 100.0}, now_ts=50.0) is False
    # 이미 결정된 것은 expired 전이 대상 아님
    assert A.is_expired({"status": "approved", "expires_at_ts": 100.0}, now_ts=200.0) is False
    print("OK is_expired는 requested + 만료시각 초과일 때만")



# ── DB 통합: 승인 authoritative store 수명주기·불변식 ──
# 모듈 전역 async engine이 pytest 함수별 이벤트 루프와 얽혀(앞선 TestClient 테스트가 풀을
# 자기 루프에 바인딩) commit이 반영되지 않는다. 깨끗한 프로세스에서 검증하도록 subprocess로
# 격리한다(test_forge_env와 같은 패턴).
import os
import subprocess
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent

_LIFECYCLE_CODE = r'''
import asyncio, uuid
from app.runtime import approvals as A
from app.db import store
from app.db.session import engine
from app.db.models import Base

async def _lifecycle():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sid = "t-appr-" + uuid.uuid4().hex[:8]
    await store.ensure_session(sid, "approval-test")
    assert await store.get_room(sid) is not None, "ensure 후 세션 없음"
    h = A.args_hash({"command": "ls"})
    try:
        aid = uuid.uuid4().hex
        await store.create_approval(aid, sid, "run1", "bash", h, "bash: ls")
        assert (await store.get_approval(aid))["status"] == "requested"

        # 멱등: 첫 결정만 반영, 재결정 무시(상태 역전 없음)
        assert await store.decide_approval(aid, sid, "approved") is True
        assert await store.decide_approval(aid, sid, "rejected") is False
        assert (await store.get_approval(aid))["status"] == "approved"

        # 다른 session 결정 불가
        aid2 = uuid.uuid4().hex
        await store.create_approval(aid2, sid, "run1", "bash", h, "bash: ls")
        assert await store.decide_approval(aid2, "someone-else", "approved") is False
        assert (await store.get_approval(aid2))["status"] == "requested"

        # consume: 승인 소비 → 재consume은 중복 실행 방지로 실패
        ok, why = await store.consume_approval(aid, sid, h)
        assert ok and why == "ok", why
        ok2, _ = await store.consume_approval(aid, sid, h)
        assert not ok2, "consumed 승인이 재실행됨"

        # args 변조 차단
        aid3 = uuid.uuid4().hex
        await store.create_approval(aid3, sid, "run1", "bash", h, "bash: ls")
        await store.decide_approval(aid3, sid, "approved")
        ok3, why3 = await store.consume_approval(aid3, sid, A.args_hash({"command": "rm -rf /"}))
        assert not ok3 and why3 == "args_changed"

        # 만료: 지난 TTL → expire_stale → expired, consume 불가
        aid4 = uuid.uuid4().hex
        await store.create_approval(aid4, sid, "run1", "bash", h, "bash: ls", ttl_seconds=-1)
        assert await store.expire_stale_approvals() >= 1
        assert (await store.get_approval(aid4))["status"] == "expired"

        # 재시작 복원: requested만 list_pending에 잡힌다
        aid5 = uuid.uuid4().hex
        await store.create_approval(aid5, sid, "run1", "write_file", h, "write a.py")
        pend = {p["id"] for p in await store.list_pending_approvals(sid)}
        assert aid5 in pend and aid2 in pend, "requested 복원 누락"
        assert aid not in pend and aid3 not in pend and aid4 not in pend
        print("APPROVAL_LIFECYCLE_OK")
    finally:
        await store.delete_room(sid)

asyncio.run(_lifecycle())
'''


def test_durable_approval_lifecycle_and_invariants():
    """멱등·session격리·consume 중복방지·args 변조·만료·pending 복원을 실제 DB로 검증."""
    r = subprocess.run([sys.executable, "-c", _LIFECYCLE_CODE], cwd=str(_BACKEND),
                       env=dict(os.environ), capture_output=True, text=True)
    assert "APPROVAL_LIFECYCLE_OK" in r.stdout, f"stdout={r.stdout}\nstderr={r.stderr}"
    print("OK durable approval: 멱등·session격리·consume중복방지·args변조·만료·pending복원")


# ── run 경로 end-to-end: 수동 승인 → consume → 실제 도구 실행(배선 회귀) ──

_RUN_APPROVAL_CODE = r'''
import asyncio, json, os, tempfile, uuid
from app.runtime.agent import AgentRuntime
from app.db import store
from app.db.session import engine
from app.db.models import Base

class FakeAdapter:
    requires_reasoning_replay = False
    def __init__(self, path, content):
        self.n = 0; self.path = path; self.content = content
    async def stream_chat(self, messages, tools=None, thinking=False, reasoning_effort=None):
        self.n += 1
        if self.n == 1:  # write_file(승인형) 호출
            yield {"tool_calls": [{"index": 0, "id": "call1", "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": self.path, "content": self.content})}}]}
        else:            # tool_call 없는 응답 → 스텝 종료
            yield {"content": "완료했습니다."}

async def _run_scenario():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ws = tempfile.mkdtemp()
    sid = "t-run-appr-" + uuid.uuid4().hex[:8]
    await store.ensure_session(sid, "run-appr", ws)
    try:
        rt = AgentRuntime()
        rt._run_ids[sid] = "run-e2e"  # run() 대신 직접 _run_role 호출이라 run 식별자를 수동 세팅
        fake = FakeAdapter("out.txt", "HELLO_APPROVED")  # 인스턴스 재사용(스텝 간 n 누적)
        rt._adapter_for = lambda m: fake
        events = []
        async def send(t, d): events.append((t, d))
        # durable idempotency: side-effect 도구(write_file) 실행 직후 즉시 save가 도는지 확인.
        # 즉시 save가 없으면 tool result 담긴 save는 '다음 스텝 시작' 1회뿐 — crash 창이 열린다.
        saves = []
        _orig_save = store.save_history
        async def _spy_save(sid_, hist):
            saves.append(any(m.get("role") == "tool" for m in hist))
            return await _orig_save(sid_, hist)
        store.save_history = _spy_save
        state = {"files_changed": [], "errors": []}
        # manual 세션(auto_approve 아님) → _request_approval이 Future로 대기하므로 task로 돌린다.
        task = asyncio.create_task(
            rt._run_role("developer", [{"role": "user", "content": "파일 써"}],
                         send, sid, ws, state, [], 0))
        aid = None
        for _ in range(300):
            await asyncio.sleep(0.02)
            ar = [d for t, d in events if t == "approval_request"]
            if ar:
                aid = ar[0]["id"]; break
        assert aid, "approval_request가 발생하지 않음"
        # 승인: PG 전이(authoritative) + 메모리 Future 해소
        assert await store.decide_approval(aid, sid, "approved") is True
        rt.resolve_approval(aid, "approve")
        await asyncio.wait_for(task, timeout=10)

        # 검증 1: 승인된 도구가 실제 실행돼 파일이 작성됨
        p = os.path.join(ws, "out.txt")
        assert os.path.isfile(p) and open(p).read() == "HELLO_APPROVED", "승인 후 파일 미작성"
        # 검증 2: 실행 직전 consume으로 approved→consumed 전이(중복 실행 방지 상태)
        a = await store.get_approval(aid)
        assert a["status"] == "consumed", f"consumed 아님: {a['status']}"
        # 검증 3: run_id가 approval에 배선됨(빈 문자열 아님)
        assert a["run_id"] == "run-e2e", f"run_id 미배선: {a['run_id']!r}"
        # 검증 4: approval_granted 이벤트 발행
        assert any(t == "approval_granted" for t, _ in events), "approval_granted 없음"
        # 검증 5: side-effect(write_file) 직후 즉시 save + 다음 스텝 시작 save → tool 담긴 save ≥2.
        # (즉시 save가 없으면 1회뿐이라 crash 시 재실행 창이 열린다.)
        assert sum(1 for s in saves if s) >= 2, f"side-effect 즉시 save 미발생: tool 담긴 save={sum(saves)}"
        store.save_history = _orig_save
        print("RUN_APPROVAL_OK")
    finally:
        store.save_history = _orig_save
        await store.delete_room(sid)

asyncio.run(_run_scenario())
'''


def test_manual_approval_runs_and_consumes_end_to_end():
    """수동 승인이 실제 run 경로에서 consume→도구 실행까지 이어지는지 검증(배선 회귀).
    subprocess로 격리(모듈 전역 async engine의 이벤트 루프 얽힘 회피)."""
    r = subprocess.run([sys.executable, "-c", _RUN_APPROVAL_CODE], cwd=str(_BACKEND),
                       env=dict(os.environ), capture_output=True, text=True)
    assert "RUN_APPROVAL_OK" in r.stdout, f"stdout={r.stdout}\nstderr={r.stderr[-2000:]}"
    print("OK 수동 승인 end-to-end: 승인→consume→실제 write_file 실행")


# ── 정합성 결함 수정 검증(취소·재시작 orphan·만료·auto_approve PG·session 격리·FK) ──

_INTEGRITY_CODE = r'''
import asyncio, uuid
from app.runtime.agent import AgentRuntime
from app.runtime import approvals as A
from app.db import store
from app.db.session import engine
from app.db.models import Base

async def _run():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sid = "t-int-" + uuid.uuid4().hex[:8]
    other = "t-oth-" + uuid.uuid4().hex[:8]
    await store.ensure_session(sid, "int")
    await store.ensure_session(other, "oth")
    h = A.args_hash({"command": "ls"})
    try:
        # (결함4/8) 만료 승인은 pending 조회에서 제외되고 결정도 불가
        e = uuid.uuid4().hex
        await store.create_approval(e, sid, "r1", "bash", h, "bash: ls", ttl_seconds=-1)
        assert e not in {p["id"] for p in await store.list_pending_approvals(sid)}, "만료가 pending에 노출"
        assert await store.decide_approval(e, sid, "approved") is False, "만료 승인이 결정됨"
        # (결함9) 만료 전이 — 한 상태만
        assert await store.expire_stale_approvals() >= 1
        assert (await store.get_approval(e))["status"] == "expired"

        # (결함3) 세션 취소 → requested→cancelled
        c = uuid.uuid4().hex
        await store.create_approval(c, sid, "r1", "bash", h, "bash: ls")
        assert await store.cancel_approvals(sid) >= 1
        assert (await store.get_approval(c))["status"] == "cancelled"

        # (결함10) 다른 session 취소·결정·consume은 이 세션 승인을 건드리지 않는다
        d = uuid.uuid4().hex
        await store.create_approval(d, sid, "r1", "bash", h, "bash: ls")
        await store.cancel_approvals(other)
        assert (await store.get_approval(d))["status"] == "requested", "다른 세션 취소가 침범"
        assert await store.decide_approval(d, other, "approved") is False, "다른 세션 결정 허용"
        await store.decide_approval(d, sid, "approved")
        ok, _ = await store.consume_approval(d, other, h)
        assert not ok, "다른 세션 consume 허용"

        # (결함1/6) 재시작 흉내 — cleanup_orphan이 모든 requested를 cancelled로, pending 비움
        o = uuid.uuid4().hex
        await store.create_approval(o, sid, "r1", "bash", h, "bash: ls")
        await store.cleanup_orphan_approvals()
        assert (await store.get_approval(o))["status"] == "cancelled", "orphan 미정리"
        assert not await store.list_pending_approvals(sid), "재시작 후 pending 잔존"

        # (결함3) auto_approve 전환: PG approved 성공분만 Future approve
        rt = AgentRuntime()
        loop = asyncio.get_running_loop()
        aid = uuid.uuid4().hex
        await store.create_approval(aid, sid, "r1", "bash", h, "bash: ls")
        f = loop.create_future()
        rt.pending_approvals[aid] = f
        rt._pending_meta[aid] = {"session_id": sid, "kind": "approval"}
        # (결함4) PG에 없는 승인은 Future를 건드리지 않는다
        ghost = uuid.uuid4().hex
        fg = loop.create_future()
        rt.pending_approvals[ghost] = fg
        rt._pending_meta[ghost] = {"session_id": sid, "kind": "approval"}
        n = await rt.resolve_pending_approvals(sid)
        assert n == 1, f"resolve_pending 전이 수 불일치: {n}"
        assert f.done() and f.result() == "approve", "PG approved인데 Future 미해소"
        assert (await store.get_approval(aid))["status"] == "approved"
        assert not fg.done(), "PG 없는 승인이 Future approve됨(도구 실행 위험)"

        # (결함12) 세션 삭제 시 Approval FK 정리
        x = uuid.uuid4().hex
        await store.create_approval(x, other, "r1", "bash", h, "bash: ls")
        await store.delete_room(other)
        assert await store.get_approval(x) is None, "세션 삭제 후 approval 잔존"
        print("INTEGRITY_OK")
    finally:
        await store.delete_room(sid)
        await store.delete_room(other)

asyncio.run(_run())
'''


def test_approval_integrity_fixes():
    """취소·재시작 orphan·만료·auto_approve PG 정합·session 격리·FK 정리를 실DB로 검증."""
    r = subprocess.run([sys.executable, "-c", _INTEGRITY_CODE], cwd=str(_BACKEND),
                       env=dict(os.environ), capture_output=True, text=True)
    assert "INTEGRITY_OK" in r.stdout, f"stdout={r.stdout}\nstderr={r.stderr[-2000:]}"
    print("OK 승인 정합성: 취소·orphan·만료·auto_approve·session격리·FK")
