"""반복 잡의 다음 실행 시각 계산 — 순수 함수, DB 의존 없음.

scheduler.py에서 import해 사용한다. 별도 모듈로 분리해 테스트가
DB 드라이버 없이도 결정론적으로 검증할 수 있게 한다.
"""
from datetime import datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfo


def compute_next(job: dict, from_utc: datetime) -> datetime | None:
    """반복 잡의 다음 실행 시각(aware UTC). one-shot이면 None."""
    rec = job.get("recurrence") or ""
    tz = ZoneInfo(job.get("timezone") or "Asia/Seoul")
    if rec == "interval":
        try:
            mins = max(1, int(job.get("recurrence_value") or "60"))
        except ValueError:
            mins = 60
        return from_utc + timedelta(minutes=mins)
    if rec == "daily":
        try:
            hh, mm = (job.get("recurrence_value") or "09:00").split(":")
            hh, mm = int(hh), int(mm)
        except ValueError:
            hh, mm = 9, 0
        local_now = from_utc.astimezone(tz)
        # DST 안전: replace()로 만든 시각이 모호(가을 전환)하면 fold=1로 이전 시각을 택한다.
        # astimezone을 쓰지 않고 tzinfo를 유지한 채 UTC로 변환해 DST 경계 오차를 없앤다.
        nxt = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0, fold=1)
        if nxt <= local_now:
            nxt += timedelta(days=1)
        return nxt.astimezone(_tz.utc)
    return None
