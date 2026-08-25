"""테스트 약화 감지(change_guard) 결정론적 검증 — git/네트워크 없이 numstat 문자열만.

실행: python -m pytest test_change_guard.py -q
"""
from app.runtime.change_guard import detect_test_weakening, is_test_path


def test_is_test_path():
    assert is_test_path("backend/test_agent.py")
    assert is_test_path("src/foo.test.ts")
    assert is_test_path("pkg/foo_test.go")
    assert is_test_path("app/__tests__/x.spec.js")
    assert is_test_path("backend/tests/test_x.py")
    # 일반 소스는 아니다
    assert not is_test_path("app/runtime/agent.py")
    assert not is_test_path("src/App.vue")


def test_detect_deleted_test_file():
    # git diff --numstat HEAD: 삭제 파일은 'added 0 / deleted N'
    ns = "0\t42\tbackend/test_login.py\n"
    w = detect_test_weakening(ns)
    assert len(w) == 1 and "삭제" in w[0] and "test_login.py" in w[0], w


def test_detect_net_reduction():
    ns = "2\t20\tbackend/test_gates.py\n"   # 단언 대거 삭제(순감소)
    w = detect_test_weakening(ns)
    assert len(w) == 1 and "순감소" in w[0], w


def test_no_warning_on_test_growth():
    ns = "30\t3\tbackend/test_new.py\n"    # 테스트 추가(증가)
    assert detect_test_weakening(ns) == []


def test_non_test_changes_ignored():
    # 소스 파일 대규모 삭제는 이 감지기 대상 아님(테스트 약화만 본다)
    ns = "0\t500\tapp/runtime/agent.py\n5\t80\tsrc/App.vue\n"
    assert detect_test_weakening(ns) == []


def test_binary_and_malformed_ignored():
    ns = "-\t-\tbackend/tests/fixture.bin\ngarbage line\n\n"
    assert detect_test_weakening(ns) == []


def test_mixed():
    ns = (
        "0\t30\tbackend/test_a.py\n"      # 삭제
        "50\t2\tbackend/test_b.py\n"      # 증가(무경고)
        "1\t15\tsrc/c.test.ts\n"          # 순감소
        "10\t10\tapp/main.py\n"           # 소스(무시)
    )
    w = detect_test_weakening(ns)
    assert len(w) == 2, w
    assert any("test_a.py" in x for x in w) and any("c.test.ts" in x for x in w), w


def test_detect_sensitive_changes():
    from app.runtime.change_guard import detect_sensitive_changes
    paths = [
        "app/runtime/agent.py",        # 일반 소스(무시)
        ".env",                        # 시크릿
        "certs/server.pem",            # 키
        ".github/workflows/ci.yml",    # CI
        "frontend/pnpm-lock.yaml",     # 의존성 lock
        ".env.example",                # 공개 예시(무시)
        "backend/id_ed25519",          # ssh 키
    ]
    w = detect_sensitive_changes(paths)
    got = " | ".join(w)
    assert ".env" in got and "server.pem" in got and "ci.yml" in got and "pnpm-lock.yaml" in got and "id_ed25519" in got, w
    assert "agent.py" not in got and ".env.example" not in got, w
    assert len(w) == 5, w


def test_detect_skipped_tests_in_diff():
    """실패하던 테스트를 삭제 대신 skip/xfail로 우회하는 것을 diff에서 감지(numstat로는 못 잡음)."""
    from app.runtime.change_guard import detect_skipped_tests
    diff = (
        "diff --git a/test_login.py b/test_login.py\n"
        "--- a/test_login.py\n"
        "+++ b/test_login.py\n"
        "@@ -1,3 +1,4 @@\n"
        " def test_login():\n"
        "+    import pytest; pytest.skip('flaky')\n"
        "     assert login()\n"
    )
    w = detect_skipped_tests(diff)
    assert w and "test_login.py" in w[0], w

    # 데코레이터 마커도 감지
    dec = ("+++ b/tests/test_api.py\n"
           "+@pytest.mark.xfail(reason='TODO')\n")
    assert detect_skipped_tests(dec), dec

    # JS .skip/.only
    js = ("+++ b/src/foo.test.js\n"
          "+  it.only('x', () => {})\n")
    assert detect_skipped_tests(js), js

    # 비테스트 파일의 .skip은 무시(테스트 파일 한정)
    non = ("+++ b/app/util.py\n"
           "+    queue.skip(3)\n")
    assert detect_skipped_tests(non) == [], non

    # skip을 제거(-)하는 변경은 경고 아님(오히려 복원)
    removed = ("+++ b/test_x.py\n"
               "-    pytest.skip('x')\n")
    assert detect_skipped_tests(removed) == [], removed
    print("OK skip/xfail/only 추가 감지(테스트 파일 한정, 추가 라인만)")
