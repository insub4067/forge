"""tool_store의 result_id 엄격검증 — save→load 왕복과 path traversal 차단을 확인한다.

STORE_DIR을 임시 디렉터리로 돌려 실제 로그를 건드리지 않는다(무DB·무샌드박스).

실행: cd backend && python -m pytest test_tool_store_id.py -q
"""
import tempfile
from pathlib import Path

from app.runtime import tool_store

tool_store.STORE_DIR = Path(tempfile.mkdtemp()) / "tool_results"


def test_legit_id_round_trips():
    """정상 생성된 id는 저장 내용을 그대로 되돌려준다."""
    rid = tool_store.save("hello world")
    assert tool_store.load(rid) == "hello world"


def test_traversal_ids_rejected():
    """traversal 형태 id는 '찾을 수 없음' 센티널로 안전 거부 — 파일 탈출·예외 없음."""
    for bad in ("tr_../../etc/passwd", "tr_..", "../x", "tr_a.b", "tr_ABCDEF0000", "tr_short", ""):
        assert tool_store.load(bad) == "오류: 잘못된 result_id"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PASS — tool_store result_id strict validation")
