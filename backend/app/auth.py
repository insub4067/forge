"""앱 레벨 토큰 게이트 — Cloudflare Access 뒤에 두는 defense-in-depth.

Access는 터널만 보호한다. uvicorn이 0.0.0.0에 바인딩되면 같은 LAN의 기기가
터널을 우회해 `/api/*`(터미널 host 셸·화면·카메라·host bash)에 인증 없이 붙는다.
FORGE_AUTH_TOKEN이 설정되면 모든 /api 요청(WebSocket 포함)과 /uploads 정적 파일에
그 토큰을 요구한다.

토큰 전달(브라우저 편의상 셋 다 허용): X-Forge-Token 헤더 / forge_token 쿠키 / ?token=.
쿠키는 같은 출처 fetch·<img>·WebSocket이 자동 전송하므로 클라이언트 수정이 최소다.
토큰 미설정 시 미들웨어는 무동작(기존 배포 무중단) — 활성화는 env + 재시작으로.
"""
from urllib.parse import parse_qs


def _extract_token(scope) -> str:
    for k, v in scope.get("headers", []):
        if k == b"x-forge-token":
            return v.decode("latin-1")
        if k == b"authorization":
            s = v.decode("latin-1")
            if s.lower().startswith("bearer "):
                return s[7:]
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == "forge_token":
                    return val
    qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    return (qs.get("token") or [""])[0]


def _needs_token(path: str) -> bool:
    """토큰이 필요한 경로. /uploads는 사용자가 첨부한 파일을 그대로 서빙하므로 /api와 같은
    보호가 필요하다 — StaticFiles로 별도 mount돼 있어 /api 조건에서 빠져 있었다.
    같은 출처 <img>·fetch는 forge_token 쿠키를 자동 전송하므로 클라이언트 변경은 없다."""
    if path.startswith("/uploads"):
        return True
    return path.startswith("/api") and path != "/api/health"


class TokenAuthMiddleware:
    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if self.token and scope.get("type") in ("http", "websocket"):
            path = scope.get("path", "")
            if _needs_token(path):
                if _extract_token(scope) != self.token:
                    if scope["type"] == "websocket":
                        await send({"type": "websocket.close", "code": 1008})
                    else:
                        await send({"type": "http.response.start", "status": 401,
                                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                        await send({"type": "http.response.body", "body": "unauthorized".encode()})
                    return
        await self.app(scope, receive, send)
