"""host 모드 bash의 쓰기 경계 — 워크스페이스 밖 쓰기를 OS 레벨에서 막는다.

왜 필요한가: host 모드는 docker 격리가 없어 방벽이 정규식 블랙리스트(_DANGEROUS)뿐이다.
블랙리스트는 명령 문자열 표면만 보므로 변수 치환·`find -delete`·`python3 -c` 같은 우회가
자명하다. 방어 가능한 경계는 "무엇을 실행하는가"가 아니라 "어디에 쓸 수 있는가"다.
파일 도구(write_file/edit_file)는 이미 `_resolve`가 워크스페이스로 제한하지만 bash는 아니었다.

방식: macOS `sandbox-exec`로 쓰기를 화이트리스트한다(읽기·네트워크·실행은 그대로).
허용: 워크스페이스, 임시 디렉터리, /dev 표준 노드, 패키지 캐시. 그 외 쓰기는 거부된다.
사용할 수 없는 환경(비 macOS, sandbox-exec 없음)이면 감싸지 않고 원래 명령을 돌려준다 —
가드는 방어를 더하는 것이지, 없다고 실행을 막지는 않는다(기존 동작 유지).
"""
import os
import shlex
import sys
import tempfile

_PROFILE = """(version 1)
(allow default)
(deny file-write*)
(allow file-write*
  (subpath (param "WS"))
  (subpath "/tmp") (subpath "/private/tmp")
  (subpath "/var/folders") (subpath "/private/var/folders")
  (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty")
  (literal "/dev/dtracehelper") (literal "/dev/stdout") (literal "/dev/stderr")
  (regex #"^/dev/fd/") (regex #"^/dev/ttys")
  (subpath (param "CACHE")) (subpath (param "NPM")) (subpath (param "PIPC")))
"""

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_profile_path: str | None = None


def available() -> bool:
    """이 호스트에서 쓰기 경계를 세울 수 있는가."""
    return sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


def _profile_file() -> str:
    """프로파일을 임시 파일로 한 번만 쓰고 재사용한다(실행마다 I/O 하지 않게)."""
    global _profile_path
    if _profile_path and os.path.exists(_profile_path):
        return _profile_path
    fd, path = tempfile.mkstemp(prefix="forge-host-guard-", suffix=".sb")
    with os.fdopen(fd, "w") as f:
        f.write(_PROFILE)
    _profile_path = path
    return path


def wrap(command: str, workspace: str) -> str:
    """명령을 쓰기 경계 안에서 실행하도록 감싼다. 불가능하면 원본을 그대로 돌려준다.

    경로는 realpath로 푼다 — macOS에서 /tmp는 /private/tmp의 심볼릭 링크라
    sandbox 규칙(실경로 기준)과 어긋나면 워크스페이스 쓰기까지 막힌다.
    """
    if not available() or not workspace:
        return command
    home = os.path.expanduser("~")
    params = {
        "WS": os.path.realpath(workspace),
        "CACHE": os.path.join(home, "Library", "Caches"),
        "NPM": os.path.join(home, ".npm"),
        "PIPC": os.path.join(home, ".cache"),
    }
    parts = [SANDBOX_EXEC, "-f", shlex.quote(_profile_file())]
    for k, v in params.items():
        parts += ["-D", shlex.quote(f"{k}={v}")]
    parts += ["/bin/sh", "-c", shlex.quote(command)]
    return " ".join(parts)
