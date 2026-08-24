"""Workspace Security Preflight — 작업 시작 전 결정적 스캔(순수 함수, LLM 없음).

FORGE는 host mode 실행 + git push + Terminal + MCP를 쓰고, 동시에
`GLOBAL_MEMORY.md`/`ROOM_MEMORY.md`/`.forge/skills/*.md`를 **system prompt에 주입**한다.
따라서 두 표면만 결정적으로 본다(ECC AgentShield의 "에이전트가 삼키는 설정 표면을 스캔"
관점을 FORGE 권한에 맞게 최소화).

1. 추적된 시크릿 파일: git이 tracking 중인 `.env`/개인키 등 → auto-push 유출 위험.
2. 주입 설정 표면: 주입되는 config 안의 prompt-injection 문구 / inline 시크릿 패턴.

기본은 fail-open이다 — 이 모듈은 판단만 하고 실행을 막지 않는다. 호출자가 HIGH일 때
사용자 확인을 걸지는 정책으로 결정한다. 애매하면 표면화하되 차단하지 않는다.
"""
import os
import re
from typing import Callable, NamedTuple, Optional


class Finding(NamedTuple):
    severity: str   # "HIGH" | "MEDIUM" | "LOW"
    category: str   # "tracked_secret" | "injection" | "inline_secret"
    path: str       # workspace 상대 경로
    detail: str


# ── 1. 추적된 시크릿 파일 (경로만 검사, 내용 안 읽음) ──────────────
# `.env.example`/`.env.sample`/`.env.template`은 관례상 공개라 제외한다.
_SECRET_BASENAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc"}
_SECRET_SUFFIXES = (".pem", ".key", ".keystore", ".p12", ".pfx")
_ENV_ALLOW = ("example", "sample", "template", "dist", "test")


def _is_secret_path(rel: str) -> Optional[str]:
    """시크릿 파일이면 사유 문자열, 아니면 None."""
    base = os.path.basename(rel).lower()
    if base in _SECRET_BASENAMES:
        return f"자격증명 파일 `{base}`가 git에 추적됨"
    if base.endswith(_SECRET_SUFFIXES):
        return f"키/인증서 파일 `{base}`가 git에 추적됨"
    if base == ".env" or (base.startswith(".env.") and base.split(".")[-1] not in _ENV_ALLOW):
        return f"환경변수 파일 `{base}`가 git에 추적됨 (push 시 유출)"
    return None


def scan_tracked_secrets(tracked_files) -> list:
    out = []
    for rel in (tracked_files or []):
        reason = _is_secret_path(str(rel))
        if reason:
            out.append(Finding("HIGH", "tracked_secret", str(rel), reason))
    return out


# ── 2. 주입 설정 표면 (내용 검사) ──────────────────────────────
# FORGE가 실제로 system prompt에 싣는 파일들 + skills 디렉터리.
_INJECTED_FIXED = ("GLOBAL_MEMORY.md", "ROOM_MEMORY.md")
_INJECTED_GLOB = (".forge/skills",)  # 하위 *.md

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"disregard\s+(the\s+)?(above|previous|prior)", re.I),
    re.compile(r"(new|updated)\s+system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|in)\b", re.I),
    re.compile(r"이전\s*(지시|명령|프롬프트)\s*(을|를)?\s*무시", re.I),
)

# inline 시크릿 패턴 — 주입 파일에 들어가면 프롬프트로 새어나간다.
_SECRET_CONTENT = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
)


def _default_read(workspace: str, rel: str) -> Optional[str]:
    path = os.path.normpath(os.path.join(workspace, rel))
    # 경로 탈출 차단.
    if not os.path.abspath(path).startswith(os.path.abspath(workspace)):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _list_injected(workspace: str) -> list:
    rels = list(_INJECTED_FIXED)
    for d in _INJECTED_GLOB:
        full = os.path.join(workspace, d)
        try:
            for name in sorted(os.listdir(full)):
                if name.endswith(".md") and name != "README.md":
                    rels.append(os.path.join(d, name))
        except OSError:
            pass
    return rels


def scan_injected_config(workspace: str, read_file: Callable[[str, str], Optional[str]] = _default_read,
                         rels: Optional[list] = None) -> list:
    out = []
    for rel in (rels if rels is not None else _list_injected(workspace)):
        text = read_file(workspace, rel)
        if not text:
            continue
        for pat in _INJECTION_PATTERNS:
            if pat.search(text):
                out.append(Finding("HIGH", "injection", rel,
                                    f"주입되는 설정에 prompt-injection 문구: `{pat.pattern[:40]}`"))
                break
        for label, pat in _SECRET_CONTENT:
            if pat.search(text):
                out.append(Finding("HIGH", "inline_secret", rel,
                                    f"주입되는 설정에 시크릿 패턴({label})"))
                break
    return out


def scan_workspace(workspace: str, *, tracked_files=None,
                   read_file: Callable[[str, str], Optional[str]] = _default_read) -> list:
    """전체 preflight. Finding 리스트를 severity 순으로 반환."""
    findings = scan_tracked_secrets(tracked_files) + scan_injected_config(workspace, read_file)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(findings, key=lambda f: order.get(f.severity, 9))


def summarize(findings: list) -> tuple:
    """(level, 한 줄 요약). 컨텍스트를 늘리지 않게 표면화용 한 줄만."""
    if not findings:
        return "OK", "security preflight: 이상 없음"
    highs = [f for f in findings if f.severity == "HIGH"]
    level = "HIGH" if highs else findings[0].severity
    head = findings[0]
    extra = f" 외 {len(findings) - 1}건" if len(findings) > 1 else ""
    return level, f"security preflight[{level}]: {head.category} {head.path} — {head.detail}{extra}"
