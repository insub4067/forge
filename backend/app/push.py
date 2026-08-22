"""Web Push 발송 — 작업 완료·승인 대기 알림.

pywebpush + VAPID. 실패(구독 만료 404/410)는 삼켜서 발송 루프가 안 죽게 한다.
"""
import json
from pathlib import Path

from pywebpush import WebPushException, webpush

from .config import settings
from . import errors as error_log


def _private_key() -> str | None:
    """pywebpush에는 PEM 내용이 아니라 파일 경로를 넘겨야 from_file로 정상 파싱된다."""
    p = Path(settings.vapid_private_key_path)
    return str(p) if p.is_file() else None


def send_one(subscription: dict, title: str, body: str, url: str = "/") -> bool:
    key = _private_key()
    if not key:
        return False
    payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=10,
        )
        return True
    except WebPushException as err:
        # 404/410 = 구독 만료. 상위에서 정리하도록 신호만 남긴다.
        error_log.record("push_failed", f"{getattr(err.response, 'status_code', '?')}: {err}", "")
        return False
    except Exception as err:
        error_log.record("push_failed", str(err), "")
        return False
