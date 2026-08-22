import time
from collections import deque

# 최근 에러를 담는 인메모리 링버퍼 (프로세스 재시작 시 초기화)
_ERRORS: deque = deque(maxlen=100)


def record(source: str, message: str, session_id: str = "") -> None:
    _ERRORS.appendleft(
        {
            "source": source,
            "message": str(message)[:2000],
            "session_id": session_id,
            "at": time.strftime("%m-%d %H:%M:%S"),
        }
    )


def recent() -> list[dict]:
    return list(_ERRORS)
