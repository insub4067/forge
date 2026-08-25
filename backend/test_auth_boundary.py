"""토큰 게이트가 보호해야 할 경로를 실제로 보호하는지 확인한다 (LLM 없음).

/uploads는 사용자가 첨부한 파일을 그대로 서빙하는데, StaticFiles로 /api와 별도 mount돼
있어 토큰 검사에서 빠져 있었다 — LAN의 다른 기기가 터널을 우회해 그대로 받아갈 수 있다.

실행: python test_auth_boundary.py  (pytest로도 수집된다)
"""
import asyncio

from app.auth import TokenAuthMiddleware, _needs_token


def test_protected_paths():
    assert _needs_token("/api/rooms")
    assert _needs_token("/uploads/abc.png")
    assert _needs_token("/uploads")
    # health는 열려 있어야 한다(로드밸런서·모니터링)
    assert not _needs_token("/api/health")
    # SPA 자산·index는 토큰 없이 떠야 로그인 화면 자체가 보인다
    assert not _needs_token("/")
    assert not _needs_token("/assets/index-abc.js")


def _call(path, token_sent):
    """미들웨어를 직접 태워 401 여부를 본다."""
    sent = []

    async def app(scope, receive, send):
        sent.append(("passed_through", None))

    async def send(msg):
        sent.append((msg["type"], msg.get("status")))

    headers = [(b"x-forge-token", token_sent.encode())] if token_sent else []
    scope = {"type": "http", "path": path, "headers": headers, "query_string": b""}
    asyncio.run(TokenAuthMiddleware(app, "secret")(scope, None, send))
    return sent


def test_uploads_rejected_without_token():
    assert ("http.response.start", 401) in _call("/uploads/x.png", "")
    assert ("http.response.start", 401) in _call("/uploads/x.png", "wrong")
    assert ("passed_through", None) in _call("/uploads/x.png", "secret")


def test_health_open_without_token():
    assert ("passed_through", None) in _call("/api/health", "")


if __name__ == "__main__":
    test_protected_paths()
    test_uploads_rejected_without_token()
    test_health_open_without_token()
    print("OK 토큰 경계(/api + /uploads)")


def test_remote_mode_fail_closed():
    """원격 운영 모드(require_auth) fail-closed: 토큰 없으면 기동 거부, 있으면 통과."""
    import pytest
    from app.auth import assert_startup_auth

    # require_auth=True + 토큰 없음 → 기동 거부(예외)
    with pytest.raises(RuntimeError):
        assert_startup_auth(True, "")
    # require_auth=True + 토큰 있음 → 통과
    assert_startup_auth(True, "secret")  # 예외 없어야 함
    # 로컬 개발 기본(require_auth=False) → 토큰 유무와 무관하게 통과(기존 동작 불변)
    assert_startup_auth(False, "")
    assert_startup_auth(False, "secret")


def test_parse_allowed_origins():
    """CORS 화이트리스트 파싱: 미설정 '*', 설정 시 그 origin만, 공백/빈 항목 정리."""
    from app.auth import parse_allowed_origins
    assert parse_allowed_origins("") == ["*"]
    assert parse_allowed_origins("   ") == ["*"]
    assert parse_allowed_origins("https://a.com") == ["https://a.com"]
    assert parse_allowed_origins("https://a.com, https://b.com ,") == ["https://a.com", "https://b.com"]
