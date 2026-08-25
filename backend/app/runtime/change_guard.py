"""변경 내용 가드 — 테스트 약화(삭제/축소) 감지(순수 함수).

Gate 오판 평가(gate_eval)의 F7: gate는 명령 exit만 보고 '통과를 위해 테스트가 약해졌는지'는
모른다(테스트를 지우면 pytest가 그냥 통과). 이 모듈은 `git diff --numstat`로 이번 변경에서
테스트 파일이 삭제되거나 라인이 순감소했는지를 결정적으로 감지해 **경고로 표면화**한다.

비차단(non-blocking)이 원칙이다 — 정당한 테스트 리팩터(중복 제거 등)도 라인이 줄 수 있어
자동으로 완료를 막으면 false-block이 생긴다. 여기서는 verdict를 바꾸지 않고 사실만 드러낸다.
차단 정책은 별도 결정 사항.
"""
import os


_TEST_NAME_HINTS = ("test_", "_test.", ".test.", ".spec.")
_TEST_DIR_HINTS = ("/tests/", "/test/", "/__tests__/")


def is_test_path(path: str) -> bool:
    """테스트 파일 경로인가 — 흔한 규약(파일명 접두/접미, tests 디렉터리)만 본다."""
    p = (path or "").replace("\\", "/")
    base = os.path.basename(p).lower()
    if any(h in base for h in _TEST_NAME_HINTS):
        return True
    low = "/" + p.lower()
    return any(h in low for h in _TEST_DIR_HINTS)


def _parse_numstat_line(line: str):
    """'added\\tdeleted\\tpath' → (added:int|None, deleted:int|None, path). 바이너리는 '-'."""
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3:
        return None
    a, d, path = parts[0], parts[1], "\t".join(parts[2:])
    ai = None if a == "-" else int(a) if a.isdigit() else None
    di = None if d == "-" else int(d) if d.isdigit() else None
    return ai, di, path


# 민감/고위험 변경 — 일반 기능 작업에서 잘 건드리지 않고, 조용히 바뀌면 위험한 파일.
# (gate_eval F6의 '무관한 파일 변경'을 의미까지 판정하진 못하지만, 이 고위험 슬라이스는 결정적.)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")
_SENSITIVE_BASENAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "requirements.txt", "requirements-dev.txt", "gemfile.lock", "cargo.lock",
    ".gitlab-ci.yml",
}
_SENSITIVE_DIR_HINTS = (
    "/.github/workflows/", "/.circleci/", "/.githooks/", "/.git/hooks/",
)
_ENV_ALLOW = ("example", "sample", "template", "dist", "test")


def _is_sensitive_path(path: str) -> str:
    """민감 파일이면 사유, 아니면 ''(빈 문자열)."""
    p = (path or "").replace("\\", "/")
    base = p.rsplit("/", 1)[-1].lower()
    low = "/" + p.lower()
    if base.endswith(_SENSITIVE_SUFFIXES):
        return "키/인증서"
    if base in _SENSITIVE_BASENAMES:
        return "의존성 lock/자격증명 설정" if "lock" in base or base in (".npmrc", ".pypirc") else "CI 설정"
    if base == ".env" or (base.startswith(".env.") and base.split(".")[-1] not in _ENV_ALLOW):
        return "환경변수(시크릿)"
    if any(h in low for h in _SENSITIVE_DIR_HINTS):
        return "CI/워크플로/깃 훅"
    return ""


def detect_sensitive_changes(paths) -> list[str]:
    """이번 변경 파일 경로 중 민감/고위험 파일을 표면화한다(비차단).

    시크릿·키·의존성 lockfile·CI 설정·git 훅 등 조용히 바뀌면 공급망/보안 위험이 되는 것들.
    verdict를 바꾸지 않고 '검토하라'는 신호만 준다."""
    out: list[str] = []
    for path in (paths or []):
        why = _is_sensitive_path(str(path))
        if why:
            out.append(f"민감 파일 변경({why}): {path}")
    return out


def detect_test_weakening(numstat: str) -> list[str]:
    """`git diff --numstat HEAD` 출력에서 테스트 약화 신호를 뽑는다.

    감지 대상:
      - 테스트 파일 삭제(added 0 + deleted>0, 파일이 사라짐)
      - 테스트 파일 라인 순감소(deleted > added) — 케이스/단언이 줄었을 가능성

    반환: 경고 문자열 리스트(비어 있으면 이상 없음). verdict는 바꾸지 않는다.
    """
    warnings: list[str] = []
    for raw in (numstat or "").splitlines():
        parsed = _parse_numstat_line(raw)
        if not parsed:
            continue
        added, deleted, path = parsed
        if not is_test_path(path):
            continue
        if added is None or deleted is None:
            continue
        if deleted > 0 and added == 0:
            warnings.append(f"테스트 파일 삭제/전면 축소: {path} (-{deleted})")
        elif deleted > added:
            warnings.append(f"테스트 라인 순감소: {path} (+{added}/-{deleted})")
    return warnings
