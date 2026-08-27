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
    # 이 헬퍼는 실제 app lifespan을 태운다. startup의 auto-resume이 켜져 있으면 테스트 DB에
    # 남은 중단 run을 '진짜로' 재개해(LLM 호출·명령 실행) 서브프로세스가 끝나지 않는다 —
    # 실제로 pytest가 19시간 매달렸다. 인증 검증에 필요 없는 startup 부작용은 꺼 둔다.
    e.setdefault("AUTO_RESUME", "0")
    e.update(env)
    # timeout 없이는 위 같은 행이 스위트 전체를 무한 대기시킨다. 멈추면 실패로 드러나게 한다.
    return subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND),
                          env=e, capture_output=True, text=True, timeout=60)


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


def test_forge_takes_priority_over_legacy_all_three_fields():
    """세 보안 필드 모두 FORGE_*가 legacy 이름보다 우선한다."""
    out = _load({
        "FORGE_AUTH_TOKEN": "new", "AUTH_TOKEN": "old",
        "FORGE_REQUIRE_AUTH": "1", "REQUIRE_AUTH": "0",
        "FORGE_ALLOWED_ORIGINS": "https://new.example", "ALLOWED_ORIGINS": "https://old.example",
    })
    assert out["auth_token"] == "new", out
    assert out["require_auth"] is True, out
    assert out["allowed_origins"] == "https://new.example", out
    print("OK 세 필드 모두 FORGE_* 우선")


def test_forge_require_auth_boolean_parsing():
    """FORGE_REQUIRE_AUTH의 boolean 파싱 — 참/거짓 표현을 올바로 해석한다."""
    for truthy in ("1", "true", "True", "yes", "on"):
        assert _load({"FORGE_REQUIRE_AUTH": truthy})["require_auth"] is True, truthy
    for falsy in ("0", "false", "False", "no", "off"):
        assert _load({"FORGE_REQUIRE_AUTH": falsy})["require_auth"] is False, falsy
    print("OK FORGE_REQUIRE_AUTH boolean 파싱")


def test_forge_allowed_origins_priority():
    """FORGE_ALLOWED_ORIGINS가 ALLOWED_ORIGINS보다 우선한다(콤마 문자열 그대로)."""
    out = _load({"FORGE_ALLOWED_ORIGINS": "https://a.example,https://b.example",
                 "ALLOWED_ORIGINS": "https://legacy.example"})
    assert out["allowed_origins"] == "https://a.example,https://b.example", out
    print("OK FORGE_ALLOWED_ORIGINS 우선순위")


def test_real_lifespan_refuses_startup_without_token():
    """실제 FastAPI lifespan을 태워 검증한다 — FORGE_REQUIRE_AUTH=1 + 토큰 없음이면 기동 거부.

    assert_startup_auth 단위 호출이 아니라 TestClient로 app lifespan startup을 실제로 실행한다.
    """
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "import sys\n"
        "try:\n"
        "    with TestClient(app):\n"
        "        pass\n"
        "    print('STARTED')\n"
        "except Exception as e:\n"
        "    print('REFUSED:' + type(e).__name__ + ':' + str(e)[:120]); sys.exit(3)\n"
    )
    # 토큰 없이 require_auth → lifespan startup에서 거부
    r = _run(code, {"FORGE_REQUIRE_AUTH": "1"})
    assert r.returncode == 3, f"기동이 거부되지 않음: {r.stdout} / {r.stderr}"
    assert "REFUSED" in r.stdout and "AUTH_TOKEN" in r.stdout, r.stdout
    # 토큰 있으면 lifespan 통과(STARTED). DB 등 다른 startup은 로컬 환경에 의존.
    r2 = _run(code, {"FORGE_REQUIRE_AUTH": "1", "FORGE_AUTH_TOKEN": "tok"})
    assert "STARTED" in r2.stdout, f"토큰 있는데 기동 실패: {r2.stdout} / {r2.stderr}"
    print("OK 실제 lifespan이 토큰 없는 FORGE_REQUIRE_AUTH=1을 거부")


if __name__ == "__main__":
    test_forge_prefixed_vars_apply()
    test_legacy_unprefixed_still_work()
    test_forge_takes_priority_over_legacy_all_three_fields()
    test_forge_require_auth_boolean_parsing()
    test_forge_allowed_origins_priority()
    test_real_lifespan_refuses_startup_without_token()
    print("\n전체 통과")
