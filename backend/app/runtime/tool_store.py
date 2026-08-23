"""도구 결과 원본 저장소 — 축약본은 컨텍스트에, 원본은 파일에 두고 필요할 때만 재조회.

큰 도구 결과(빌드/테스트/grep 로그 등)를 컨텍스트에 통째로 누적하지 않는다. 축약본과
result_id만 컨텍스트에 남기고, 원본은 여기에 저장한다. 모델이 더 필요하면 read_tool_result
도구로 원본 일부를 다시 가져온다(공격적 압축을 해도 정보 손실이 복구 가능해지는 안전망).
파일 기반이라 재시작에도 살아남는다.
"""
import uuid
from pathlib import Path

# eventlog(backend/logs)와 같은 위치 아래 — 이 디렉터리는 .gitignore 대상이라 커밋되지 않는다.
# (tool_store.py는 backend/app/runtime/ 이라 backend까지 세 단계 상위.)
STORE_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "tool_results"


def save(text: str) -> str:
    """원본을 저장하고 result_id를 반환한다."""
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    rid = "tr_" + uuid.uuid4().hex[:10]
    (STORE_DIR / f"{rid}.txt").write_text(text, encoding="utf-8")
    return rid


def load(result_id: str, offset: int = 0, limit: int = 4000) -> str:
    """저장된 원본의 [offset:offset+limit] 구간을 반환한다. path traversal은 차단."""
    if not result_id or "/" in result_id or "." in result_id.replace("tr_", "", 1):
        return "오류: 잘못된 result_id"
    p = STORE_DIR / f"{result_id}.txt"
    if not p.is_file():
        return "오류: 결과를 찾을 수 없습니다(만료·무효한 result_id)"
    text = p.read_text(encoding="utf-8", errors="replace")
    limit = max(1, min(limit, 20_000))
    chunk = text[offset:offset + limit]
    tail = ""
    if len(text) > offset + limit:
        tail = f"\n\n... (전체 {len(text)}자 중 {offset}~{offset + len(chunk)} 표시 — 더 보려면 offset 조정) ..."
    return chunk + tail
