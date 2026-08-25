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
