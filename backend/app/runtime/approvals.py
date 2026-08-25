"""Durable Approval 상태기계 — 순수 로직(DB 비의존). PostgreSQL을 승인의 authoritative store로
쓰되, 상태 전이·보안 판정은 여기 순수 함수로 두어 결정적으로 검증한다.

상태: requested → approved | rejected | expired | cancelled → consumed
불변식:
  - requested 상태만 approved/rejected로 결정할 수 있다(멱등 — 이미 결정된 것 재결정 불가).
  - 승인된 작업 실행 직전 consume한다: approved + 같은 session + args_hash 일치 + 미만료여야 한다.
  - args가 바뀌면 기존 승인을 쓸 수 없다(args_hash 재검증).
  - 다른 session의 승인은 처리·실행할 수 없다.
  - 만료된 승인은 실행할 수 없다.
"""
from __future__ import annotations

import hashlib
import json

TERMINAL = {"rejected", "expired", "cancelled", "consumed"}


def normalize_args(args) -> str:
    """tool args를 결정적 문자열로 정규화(키 정렬). 직렬화 불가 값은 문자열화로 폴백."""
    try:
        return json.dumps(args or {}, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(args), ensure_ascii=False)


def args_hash(args) -> str:
    """정규화된 args의 sha256. 승인 시 저장하고 실행 직전 재검증해 변조를 막는다."""
    return hashlib.sha256(normalize_args(args).encode("utf-8")).hexdigest()


def can_decide(current_status: str) -> bool:
    """requested 상태만 approved/rejected로 결정 가능(멱등성 — 재결정·역전 방지)."""
    return current_status == "requested"


def can_consume(approval: dict, req_session_id: str, current_args_hash: str,
                now_ts: float) -> tuple[bool, str]:
    """승인된 작업을 실제 실행 직전 consume할 수 있는지. (ok, reason).

    중복 실행 방지·args 변조 차단·session 격리·만료 차단을 한곳에서 판정한다.
    """
    if approval.get("session_id") != req_session_id:
        return False, "session_mismatch"
    if approval.get("status") != "approved":
        return False, f"status_{approval.get('status')}"
    exp = approval.get("expires_at_ts")
    if exp and now_ts > exp:
        return False, "expired"
    if approval.get("args_hash") != current_args_hash:
        return False, "args_changed"
    return True, "ok"


def is_expired(approval: dict, now_ts: float) -> bool:
    """requested 승인이 만료시각을 넘겼는지(만료 전이 대상). 이미 결정된 것은 대상 아님."""
    exp = approval.get("expires_at_ts")
    return bool(exp and approval.get("status") == "requested" and now_ts > exp)
