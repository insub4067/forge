"""첨부 이미지가 모델에 실제로 전달되는지 검증 (LLM 없음).

실제 버그: 프론트가 업로드 응답의 상대 경로(`/uploads/abc.png`)를 image_urls로 보내면
/api/chat이 그 문자열을 그대로 모델에 넘겼다. 모델은 그 경로를 가져올 수 없어
"첨부 이미지를 확인할 수 없습니다"라고 답했다 — 조용히 실패하는 종류라 테스트로 고정한다.

실행: python test_chat_images.py  (pytest로도 수집된다)
"""
import base64

from app.api.routes import UPLOADS_DIR, _inline_upload

PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _write(name: str) -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / name).write_bytes(PNG)


def test_upload_url_becomes_data_uri():
    """업로드 경로는 모델이 읽을 수 있는 base64 data URI로 바뀐다."""
    name = "_test_inline.png"
    _write(name)
    try:
        out = _inline_upload(f"/uploads/{name}")
        assert out.startswith("data:image/png;base64,"), out[:40]
        # 실제 바이트가 그대로 실려야 한다
        assert base64.b64decode(out.split(",", 1)[1]) == PNG
    finally:
        (UPLOADS_DIR / name).unlink(missing_ok=True)


def test_missing_file_is_left_alone():
    """파일이 없으면 원본을 그대로 둔다(크래시 금지)."""
    assert _inline_upload("/uploads/_nope_.png") == "/uploads/_nope_.png"


def test_external_url_is_left_alone():
    """외부 http URL은 모델이 직접 가져갈 수 있으므로 건드리지 않는다."""
    for u in ("https://example.com/a.png", "data:image/png;base64,AAAA", ""):
        assert _inline_upload(u) == u


def test_path_traversal_is_contained():
    """`/uploads/` 밖으로 나가는 경로를 읽지 않는다(basename만 사용)."""
    out = _inline_upload("/uploads/../../../etc/passwd")
    # basename만 취하므로 uploads 안의 'passwd'를 찾고, 없으면 원본 반환
    assert out.startswith("/uploads/"), out


def test_query_string_is_stripped():
    """캐시 버스터(?t=123)가 붙어도 파일을 찾는다."""
    name = "_test_qs.png"
    _write(name)
    try:
        out = _inline_upload(f"/uploads/{name}?t=12345")
        assert out.startswith("data:image/png;base64,")
    finally:
        (UPLOADS_DIR / name).unlink(missing_ok=True)


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("첨부 이미지 전달 테스트 통과 ✓")
