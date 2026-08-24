import json
import os
import time
from collections import deque
from pathlib import Path

# 최근 에러를 담는 인메모리 링버퍼 (프로세스 재시작 시 초기화)
_ERRORS: deque = deque(maxlen=100)

# durable 로그: record() 호출 때마다 JSONL 한 줄씩 append (eventlog.py 방식)
LOG_DIR = Path(os.environ.get("FORGE_LOG_DIR")
               or Path(__file__).resolve().parent.parent / "logs")


def record(source: str, message: str, session_id: str = "") -> None:
    entry = {
        "source": source,
        "message": str(message)[:2000],
        "session_id": session_id,
        "at": time.strftime("%m-%d %H:%M:%S"),
    }
    _ERRORS.appendleft(entry)
    _append_log(entry)


def _append_log(entry: dict) -> None:
    """errors.jsonl에 한 줄 append. 로깅 실패가 실행을 막지 않게 조용히 무시."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / "errors.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def recent() -> list[dict]:
    return list(_ERRORS)
