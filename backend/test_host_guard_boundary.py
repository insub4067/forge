"""host 모드 쓰기 경계 — 이미 존재하는 워크스페이스 밖 파일을 지키는가 (macOS 전용).

test_host_write_guard.py는 밖으로의 **파일 생성**(echo>·python·tee)이 막히는지 본다.
여기서 메우는 빈틈: 가드의 실제 위협 모델은 "새 파일 생성"이 아니라 **기존 바깥 파일의
파괴적 변경**이다 — rm(삭제)과 제자리 덮어쓰기. sandbox 프로파일의 (deny file-write*)는
unlink·truncate도 포함하지만, 그 경로는 어느 테스트도 밟지 않았다.

비 macOS·sandbox-exec 부재 환경에선 available()이 False → 모듈 전체가 skip 된다
(Linux CI에서는 실행되지 않고, macOS 로컬에서만 실제 sandbox-exec를 돌린다).

실행: python test_host_guard_boundary.py  (pytest로도 수집된다)
"""
import os
import subprocess
import sys
import tempfile

import pytest

from app.sandbox import host_guard

pytestmark = pytest.mark.skipif(
    not host_guard.available(),
    reason="쓰기 경계는 macOS sandbox-exec에서만 적용된다",
)


def _sh(cmd: str) -> tuple[int, str]:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def test_delete_of_existing_outside_file_is_blocked():
    """워크스페이스 밖에 이미 있는 파일을 rm 해도 살아남아야 한다 — 삭제도 file-write*다."""
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    victim = os.path.join(os.path.expanduser("~"), "_forge_guard_survivor.txt")
    with open(victim, "w") as f:
        f.write("keep\n")
    try:
        rc, _ = _sh(host_guard.wrap(f"rm -f {victim}", ws))
        assert rc != 0, "밖 파일 삭제가 허용됐다"
        assert os.path.exists(victim), "차단됐다는데 파일이 지워졌다"
    finally:
        os.path.exists(victim) and os.remove(victim)


def test_inplace_overwrite_of_existing_outside_file_is_blocked():
    """밖에 있는 기존 파일을 덮어써도 내용이 그대로여야 한다 — truncate도 막힌다."""
    ws = tempfile.mkdtemp(prefix="forge-guard-")
    victim = os.path.join(os.path.expanduser("~"), "_forge_guard_untouched.txt")
    with open(victim, "w") as f:
        f.write("original\n")
    try:
        _sh(host_guard.wrap(f"echo hacked > {victim}", ws))
        with open(victim) as f:
            assert f.read() == "original\n", "밖 파일이 덮어써졌다"
    finally:
        os.path.exists(victim) and os.remove(victim)


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
