"""host 모드 bash의 쓰기 경계 (P0-C #3) — 실제 sandbox-exec로 검증, LLM 없음.

docker 격리가 없는 host 모드에서 유일한 방벽이 정규식 블랙리스트뿐이었다. 블랙리스트는
명령 문자열 표면만 보므로 `python3 -c`·`find -delete`·변수 치환으로 자명하게 우회된다.
여기서 고정하는 것: **워크스페이스 밖 쓰기는 무슨 수를 써도 실패한다**, 그리고
**정상 개발 명령(git·pytest·파일 생성)은 그대로 동작한다**(가드가 게이트를 거짓 실패시키지 않게).

실행: python test_host_write_guard.py  (pytest로도 수집된다)
"""
import asyncio
import os
import subprocess
import sys
import tempfile

import pytest

from app.sandbox import host_guard
from app.sandbox.executor import DockerSandbox

darwin_only = pytest.mark.skipif(not host_guard.available(),
                                 reason="쓰기 경계는 macOS sandbox-exec에서만 적용된다")


def _sh(cmd: str) -> tuple[int, str]:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


@darwin_only
def test_write_inside_workspace_is_allowed():
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    rc, out = _sh(host_guard.wrap(f"echo ok > {ws}/a.txt && cat {ws}/a.txt", ws))
    assert rc == 0 and "ok" in out, out


@darwin_only
def test_write_outside_workspace_is_denied():
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    target = os.path.join(os.path.expanduser("~"), "_forge_guard_should_not_exist.txt")
    rc, _ = _sh(host_guard.wrap(f"echo bad > {target}", ws))
    assert rc != 0, "워크스페이스 밖 쓰기가 허용됐다"
    assert not os.path.exists(target), "차단됐다는데 파일이 생겼다"


@darwin_only
def test_blacklist_bypasses_are_still_blocked():
    """정규식 블랙리스트가 못 잡는 우회들도 쓰기 경계에서는 막힌다 — 이 테스트가 존재 이유다."""
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    home = os.path.expanduser("~")
    cases = {
        "python": f"python3 -c \"open('{home}/_forge_guard_py.txt','w').write('x')\"",
        "변수 치환": f"D={home}; echo x > $D/_forge_guard_var.txt",
        "tee": f"echo x | tee {home}/_forge_guard_tee.txt",
    }
    for label, cmd in cases.items():
        _sh(host_guard.wrap(cmd, ws))
        made = [f for f in ("_forge_guard_py.txt", "_forge_guard_var.txt", "_forge_guard_tee.txt")
                if os.path.exists(os.path.join(home, f))]
        assert not made, f"{label} 우회로 파일이 생성됨: {made}"


@darwin_only
def test_real_dev_commands_still_work():
    """가드가 정상 작업을 깨면 게이트가 거짓 실패한다 — git·pytest가 경계 안에서 돌아야 한다."""
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    _sh(f"cd {ws} && git init -q . && git config user.email t@t && git config user.name t")
    with open(os.path.join(ws, "f.txt"), "w") as f:
        f.write("x\n")
    with open(os.path.join(ws, "test_s.py"), "w") as f:
        f.write("def test_ok():\n    assert 1\n")

    rc, out = _sh(host_guard.wrap(f"cd {ws} && git add -A && git commit -qm t && git log --oneline -1", ws))
    assert rc == 0, f"git이 경계 안에서 실패: {out}"
    rc, out = _sh(host_guard.wrap(f"cd {ws} && {sys.executable} -m pytest -q test_s.py", ws))
    assert rc == 0 and "1 passed" in out, f"pytest가 경계 안에서 실패: {out}"


def test_guard_is_transparent_when_unavailable(monkeypatch):
    """비 macOS·sandbox-exec 부재 환경에선 감싸지 않는다 — 방어를 더할 뿐 실행을 막지 않는다."""
    monkeypatch.setattr(host_guard, "available", lambda: False)
    assert host_guard.wrap("echo hi", "/tmp/x") == "echo hi"
    # 워크스페이스가 없으면(=경계를 정의할 수 없으면) 그대로 둔다
    monkeypatch.setattr(host_guard, "available", lambda: True)
    assert host_guard.wrap("echo hi", "") == "echo hi"


def test_setting_off_disables_wrapping(monkeypatch):
    """HOST_WRITE_GUARD=0이면 감싸지 않는다(탈출구)."""
    from app.config import settings
    ex = DockerSandbox(workspace="/tmp")
    monkeypatch.setattr(settings, "host_write_guard", False)
    assert ex._guarded("echo hi") == "echo hi"


@darwin_only
def test_executor_host_path_applies_guard():
    """실행기 경로(_run_host)가 실제로 경계를 적용한다 — wrap 단위 테스트만으로는 배선을 못 본다."""
    from app.config import settings
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    ex = DockerSandbox(workspace=ws)
    if not settings.host_write_guard:
        pytest.skip("가드가 꺼져 있음")
    target = os.path.join(os.path.expanduser("~"), "_forge_guard_exec.txt")
    out = asyncio.run(ex._run_host(f"echo bad > {target}", 20))
    assert not os.path.exists(target), f"실행기 경로에서 밖 쓰기가 통과됨: {out}"
    out = asyncio.run(ex._run_host("echo inside > ok.txt && cat ok.txt", 20))
    assert "inside" in out, out


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
