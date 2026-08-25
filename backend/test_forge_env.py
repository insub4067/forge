"""FORGE_* 보안 환경변수가 실제 Settings에 적용되는지 subprocess로 검증한다.

문서·주석·기동 에러 메시지는 FORGE_AUTH_TOKEN / FORGE_REQUIRE_AUTH /
FORGE_ALLOWED_ORIGINS를 안내하지만, 접두사 없는 이름만 읽히던 회귀가 있었다
(FORGE_REQUIRE_AUTH=1이 무시돼 외부 노출 배포의 fail-closed가 안 켜짐).

별도 프로세스에서 실제 env 로딩과 lifespan fail-closed 게이트까지 확인한다.
실행: cd backend && .venv/bin/python -m pytest test_forge_env.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent


def _run(code: str, env: dict) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    # 부모 환경에 남아있을 수 있는 auth 관련 변수를 제거해 격리한다.
    for k in ("FORGE_AUTH_TOKEN", "AUTH_TOKEN", "FORGE_REQUIRE_AUTH", "REQUIRE_AUTH",
              "FORGE_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"):
        e.pop(k, None)
    e.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND),
                          env=e, capture_output=True, text=True)


def _load(env: dict) -> dict:
    code = ("import json;from app.config import Settings;s=Settings();"
            "print(json.dumps({'auth_token':s.auth_token,'require_auth':s.require_auth,"
            "'allowed_origins':s.allowed_origins}))")
    r = _run(code, env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_forge_prefixed_vars_apply():
    out = _load({"FORGE_AUTH_TOKEN": "tok", "FORGE_REQUIRE_AUTH": "1",
                 "FORGE_ALLOWED_ORIGINS": "https://a.example"})
    assert out["auth_token"] == "tok", out
    assert out["require_auth"] is True, out
    assert out["allowed_origins"] == "https://a.example", out
    print("OK FORGE_* 접두사 변수가 실제 적용됨")


def test_legacy_unprefixed_still_work():
    out = _load({"AUTH_TOKEN": "legacy", "REQUIRE_AUTH": "1"})
    assert out["auth_token"] == "legacy" and out["require_auth"] is True, out
    print("OK 기존 접두사 없는 변수도 계속 동작")


def test_forge_takes_priority_over_legacy():
    out = _load({"FORGE_AUTH_TOKEN": "new", "AUTH_TOKEN": "old"})
    assert out["auth_token"] == "new", out
    print("OK FORGE_* 우선순위 > 접두사 없는 이름")


def test_lifespan_fail_closed_with_forge_require_auth():
    """FORGE_REQUIRE_AUTH=1인데 토큰이 없으면 기동 게이트가 거부한다."""
    code = ("from app.config import Settings;from app.auth import assert_startup_auth;"
            "s=Settings();assert_startup_auth(s.require_auth, s.auth_token);print('OK')")
    # 토큰 없음 → 거부
    r = _run(code, {"FORGE_REQUIRE_AUTH": "1"})
    assert r.returncode != 0, "토큰 없이 fail-closed가 통과했다"
    assert "AUTH_TOKEN" in (r.stderr + r.stdout)
    # 토큰 있음 → 통과
    r2 = _run(code, {"FORGE_REQUIRE_AUTH": "1", "FORGE_AUTH_TOKEN": "tok"})
    assert r2.returncode == 0, r2.stderr
    print("OK lifespan fail-closed가 FORGE_REQUIRE_AUTH/FORGE_AUTH_TOKEN으로 동작")


if __name__ == "__main__":
    test_forge_prefixed_vars_apply()
    test_legacy_unprefixed_still_work()
    test_forge_takes_priority_over_legacy()
    test_lifespan_fail_closed_with_forge_require_auth()
    print("\n전체 통과")
