"""모든 에이전트 동작을 추적 가능하게 남기는 append-only 이벤트 로그.

send()가 이미 모든 동작(role 전환·도구 호출/결과·승인·압축·완료)을 지나가므로
거기 한 곳만 탭하면 전부 잡힌다. durable하게 JSONL 한 줄씩 append한다
(Redis/DB 테이블 없이 — 파일로 충분, grep 가능).

한 줄 형식: {"ts", "session_id", "seq", "type", "data"}
"""
import json
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_MAX_DATA_CHARS = 1500  # 도구 결과 등 큰 페이로드는 잘라 로그 비대화 방지


def _trim(data: dict) -> dict:
    """큰 문자열 필드(도구 결과·diff 등)를 잘라 로그 크기를 억제한다."""
    out = {}
    for k, v in (data or {}).items():
        if isinstance(v, str) and len(v) > _MAX_DATA_CHARS:
            out[k] = v[:_MAX_DATA_CHARS] + f"…(+{len(v) - _MAX_DATA_CHARS}자)"
        else:
            out[k] = v
    return out


def record(session_id: str, seq: int, event_type: str, data: dict) -> None:
    """이벤트 한 건을 오늘 날짜 파일에 append한다. 로깅 실패가 실행을 막지 않게 조용히 무시."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.utcnow()
        line = {
            "ts": now.isoformat(),
            "session_id": session_id,
            "seq": seq,
            "type": event_type,
            "data": _trim(data),
        }
        path = LOG_DIR / f"events-{now:%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass


def tail(session_id: str = "", limit: int = 200) -> list[dict]:
    """최근 이벤트를 반환한다(추적 조회용). session_id로 필터 가능."""
    if not LOG_DIR.is_dir():
        return []
    files = sorted(LOG_DIR.glob("events-*.jsonl"))
    rows: list[dict] = []
    for p in reversed(files):
        try:
            for ln in reversed(p.read_text(encoding="utf-8").splitlines()):
                try:
                    row = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if session_id and row.get("session_id") != session_id:
                    continue
                rows.append(row)
                if len(rows) >= limit:
                    return list(reversed(rows))
        except OSError:
            continue
    return list(reversed(rows))
