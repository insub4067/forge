import asyncio
import re
from pathlib import Path

from ..config import settings

# write_file 성공 시 반환 접두사(사용자 표시 문자열 겸 내부 성공 marker). 런타임의
# 히스토리 접기(_fold_old_write_args)가 이 상수를 import해 성공 판정에 쓴다 — 표시 문구를
# 여기서 바꾸면 접기 판정도 함께 따라가 조용히 중단되지 않는다.
WRITE_OK_PREFIX = "파일을 작성했습니다"

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file's contents. Returns the file text with line numbers. "
                "Reading a large file whole returns only a SYMBOL MAP (definition lines), "
                "not the full text — then call find_symbol(path, name) for the function/class "
                "you need, or offset/limit for a specific line range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative path"},
                    "offset": {"type": "integer", "description": "1-based start line (optional). Read from here."},
                    "limit": {"type": "integer", "description": "Max lines to read from offset (optional)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories at a path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative directory path"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents for a regex pattern. Skips node_modules and .git.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "include": {"type": "string", "description": "Optional glob filter, e.g. '*.py' or 'src/**/*.ts'"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative file path"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace the first occurrence of old_string with new_string in a file. old_string must match exactly including whitespace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command in a Docker sandbox. Use for git, build, tests, package managers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_frontend",
            "description": "프론트엔드를 빌드한다(npm run build). 샌드박스가 아니라 host에서 node로 실행되므로 dist가 갱신돼 배포된다. frontend/ 소스(App.vue·style.css 등)를 고친 뒤 화면에 반영하려면 이 도구를 호출한다.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "작업 중 사용자 확인·의견이 필요할 때 질문한다. 사용자 답변이 도구 결과로 반환된다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "사용자에게 물을 질문"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "선택지 (선택형 질문일 때 제공)",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_tasks",
            "description": "작업 계획을 태스크 목록으로 등록·갱신한다. 작업 시작 시 계획을 등록하고, 진행에 따라 상태와 진행률을 갱신한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["todo", "working"],
                                    "description": "todo 또는 working만 설정한다. testing/done은 프로세스(검증 게이트)가 소유하므로 직접 설정하지 않는다.",
                                },
                                "progress": {"type": "integer", "minimum": 0, "maximum": 100},
                            },
                            "required": ["title"],
                        },
                    }
                },
                "required": ["tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_gates",
            "description": (
                "사용자 요구사항을 검증 가능한 acceptance gate로 분해해 등록한다. 구현 전에 호출한다. "
                "각 gate는 심볼 존재가 아니라 observable behavior로 변환하라(예: 소스에 함수명이 있는지가 "
                "아니라, 엔드포인트를 실제로 호출/테스트해 기대 동작이 나오는지). verification_method는 "
                "cwd=workspace에서 sh -c로 실행. "
                "★통과 규칙: passed는 (exit 0 AND expected_result 문자열이 stdout에 실제로 출력)일 때만 "
                "부여된다. 따라서 verification_method는 expected_result를 반드시 stdout에 찍어야 한다. "
                "`grep -q`(출력 없음)나 조용한 명령은 통과 불가 — 대신 `grep -c`/`grep`(매칭이 출력됨) 또는 "
                "`<검사> && echo PASS`처럼 만들고 expected_result를 그 출력('PASS' 등)에 맞춰라. exit 0만으로는 "
                "통과되지 않는다(unavailable 처리). 실행 가능한 검증을 만들 수 없으면 status=unavailable + "
                "failure_reason. passed/failed는 절대 직접 설정하지 않는다(프로세스가 실제 실행 후 부여)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "요구사항 (예: 로그인)"},
                                "description": {"type": "string", "description": "요구사항 상세"},
                                "verification_method": {"type": "string", "description": "실행 가능한 검증 명령(sh -c, cwd=workspace). expected_result를 stdout에 반드시 출력해야 한다(grep -q 같은 조용한 명령 금지)."},
                                "expected_result": {"type": "string", "description": "verification_method의 stdout에 실제로 찍혀야 하는 문자열. 안 찍히면 통과 못 한다(exit 0이어도)."},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "working", "blocked", "abandoned", "unavailable"],
                                    "description": "pending/working/blocked/abandoned/unavailable만 설정한다. passed/failed는 프로세스 전용.",
                                },
                                "failure_reason": {"type": "string", "description": "blocked/abandoned/unavailable일 때 사유"},
                                "requirement_id": {"type": "string", "description": "이 gate가 검증하는 Task IR 요구사항 id(예: R1). 있으면 연결, 없으면 빈 값(선택)."},
                            },
                            "required": ["title"],
                        },
                    }
                },
                "required": ["gates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": (
                "이번 작업에서 발견한, 앞으로 반복될 만한 문제 해결 절차를 재사용 가능한 skill로 저장한다. "
                "단순 사실(memory)이 아니라 '이런 상황에서 이렇게 확인·수정한다'는 절차를 담는다. "
                "여러 단계로 성공했고 재사용 가치가 확실할 때만 호출한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "skill 식별자 (예: fastapi-sse-debug)"},
                    "content": {"type": "string", "description": "절차를 담은 마크다운. 언제 쓰는지, 확인 순서, 명령/체크포인트."},
                    "scope": {"type": "string", "enum": ["project", "global"], "description": "project(기본, 이 프로젝트 전용) | global(모든 workspace 재사용). 특정 파일명·경로·도메인에 묶이지 않고 여러 코드베이스에서 재사용 가능한 범용 절차만 global. 애매하면 project."},
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": "파일에서 함수/클래스/심볼 정의를 찾아 그 범위만 반환한다. 큰 파일 전체를 read_file하는 대신 특정 심볼만 볼 때 써서 토큰을 아낀다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative path"},
                    "symbol": {"type": "string", "description": "함수/클래스/변수 이름"},
                },
                "required": ["path", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_tool_result",
            "description": "축약된 도구 결과의 원본 일부를 다시 가져온다. 큰 결과는 축약본+result_id로만 컨텍스트에 남으므로, 더 필요할 때만 이 도구로 원본을 조회한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result_id": {"type": "string", "description": "축약본에 표시된 result_id (예: tr_ab12cd34ef)"},
                    "offset": {"type": "integer", "description": "원본에서 읽기 시작할 문자 위치(기본 0)"},
                    "limit": {"type": "integer", "description": "가져올 문자 수(기본 4000, 최대 20000)"},
                },
                "required": ["result_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check",
            "description": (
                "로컬에서 뜬 웹앱을 headless 브라우저로 열어 실제로 렌더되는지 검증한다. "
                "빌드 통과가 '실제로 동작함'을 뜻하지 않으므로, 프론트를 고친 뒤 이 도구로 "
                "콘솔 에러·uncaught 예외·핵심 셀렉터 렌더를 직접 확인해 self-repair하라. "
                "로컬 오리진(localhost/127.0.0.1)만 허용한다. 읽기 전용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "확인할 로컬 URL(기본 http://127.0.0.1:8790)"},
                    "selectors": {
                        "type": "array", "items": {"type": "string"},
                        "description": "렌더 확인할 CSS 셀렉터 목록(선택). 예: ['header', '.composer-input']",
                    },
                },
                "required": [],
            },
        },
    },
]

# chat 에이전트는 읽기·질문만 — 코드 수정/실행 도구는 제외한다.
CHAT_TOOLS = [
    t for t in TOOL_SCHEMAS
    if t["function"]["name"] in {"read_file", "list_dir", "grep", "find_symbol", "ask_user", "browser_check"}
]

# build_frontend는 host에서 npm run build를 직접 실행(Docker 우회) — 승인 필요.
APPROVAL_REQUIRED = {"write_file", "edit_file", "bash", "save_skill", "build_frontend"}
# host 모드에서 bash가 호스트에 직접 닿으므로, FORGE를 실행 중인 백엔드 프로세스를
# 스스로 죽이는 것을 막는다(자기 세션 자멸·완전 다운 방지). 백엔드 변경 적용을 위한
# 재시작은 FORGE가 아니라 사람이/슈퍼바이저가 한다. 빌드는 build_frontend 도구를 쓴다.
# git push는 사용자가 명시적으로 허용함 — FORGE가 자기 작업을 origin까지 올릴 수 있다.
BLOCKED_COMMANDS = ["rm -rf", "sudo ", "chmod 777",
                    "kill ", "killall", "pkill", "uvicorn"]


def _resolve(workspace: str, input_path: str) -> Path:
    p = Path(input_path)
    if not p.is_absolute():
        p = Path(workspace) / p
    p = p.resolve()
    root = Path(workspace).resolve()
    if p != root and root not in p.parents:
        raise PermissionError(f"작업 영역 밖 경로는 접근할 수 없습니다: {input_path}")
    return p


def _read_file_capped(path: Path) -> str:
    """파일을 크기 상한 안에서 읽는다. 거대 파일(수백 MB 로그 등)을 통째로 메모리에 올려
    서버를 먹통으로 만드는 것을 방지한다. 상한을 넘으면 앞부분만 + 안내."""
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > _READ_FILE_MAX_BYTES:
        with open(path, "rb") as f:
            raw = f.read(_READ_FILE_MAX_BYTES)
        head = raw.decode("utf-8", errors="replace")
        return (head + f"\n\n... (파일이 {size:,} bytes로 너무 큽니다 — 앞 "
                f"{_READ_FILE_MAX_BYTES:,} bytes만 표시. offset/limit으로 범위를 지정하세요)")
    return path.read_text(encoding="utf-8", errors="replace")


def _list_tree(path: Path, depth: int, budget: dict | None = None) -> list[str]:
    import time
    if budget is None:
        budget = {"n": 0, "deadline": time.monotonic() + _LISTDIR_MAX_SECONDS, "capped": False}
    lines: list[str] = []
    try:
        entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name))
    except PermissionError:
        return [f"{'  ' * depth}? (접근 불가)"]
    for e in entries:
        # 항목 수·시간 상한 — 홈처럼 거대한 트리에서 폭주해 루프를 막지 않게 조기 종료.
        if budget["n"] >= _LISTDIR_MAX_ENTRIES or time.monotonic() > budget["deadline"]:
            budget["capped"] = True
            return lines
        if e.name in {"node_modules", ".git", "__pycache__", ".venv", "dist", ".next", "build"}:
            continue
        if e.is_symlink():  # 심링크 루프로 무한 재귀 방지
            continue
        budget["n"] += 1
        if e.is_dir():
            lines.append(f"{'  ' * depth}{e.name}/")
            if depth < 2:
                lines.extend(_list_tree(e, depth + 1, budget))
        else:
            lines.append(f"{'  ' * depth}{e.name}")
    return lines


# grep은 이벤트 루프를 블록하는 동기 재귀다 — 홈 디렉터리처럼 큰 트리에서 폭주해 서버를
# 먹통으로 만든 사고가 있었다(워크스페이스가 /Users/insub였고 수만 파일을 훑었다).
# 방문 파일 수·경과 시간·결과 수에 상한을 두고, execute_tool은 이걸 executor로 돌린다.
_GREP_MAX_FILES = 20000
_GREP_MAX_HITS = 100
_GREP_MAX_SECONDS = 8.0
# 파일시스템 도구 공용 상한 — 동기 재귀/대용량 읽기가 이벤트 루프를 막고 서버를 먹통으로
# 만드는 것을 방지한다(홈 디렉터리·거대 로그 파일 등).
_LISTDIR_MAX_ENTRIES = 2000   # 트리에 나열할 최대 항목 수
_LISTDIR_MAX_SECONDS = 5.0
_READ_FILE_MAX_BYTES = 5_000_000  # read_file/find_symbol이 통째로 읽는 최대 크기(5MB)


def _grep(path: Path, pattern: str, include: str | None, out: list[str],
          budget: dict | None = None) -> None:
    import re
    import time

    if budget is None:
        budget = {"files": 0, "deadline": time.monotonic() + _GREP_MAX_SECONDS}
    regex = re.compile(pattern)
    try:
        entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name))
    except PermissionError:
        return
    for e in entries:
        if len(out) >= _GREP_MAX_HITS or budget["files"] >= _GREP_MAX_FILES \
                or time.monotonic() > budget["deadline"]:
            return
        if e.name in {"node_modules", ".git", "__pycache__", ".venv", ".venv", "dist", ".next", "build"}:
            continue
        if e.is_symlink():  # 심링크 루프로 무한 재귀 방지
            continue
        if e.is_dir():
            _grep(e, pattern, include, out, budget)
            continue
        if include and not e.match(include):
            continue
        budget["files"] += 1
        try:
            text = e.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                out.append(f"{e}:{i}: {line.strip()}")
                if len(out) >= _GREP_MAX_HITS:
                    return


def _make_diff(old_text: str, new_text: str, path: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


READ_FILE_OUTLINE_THRESHOLD = 400  # 이 줄수를 넘는 파일을 통째로 읽으면 심볼 지도로 대체

_SYM_DEF = re.compile(
    r"^\s*(?:async\s+)?(?:export\s+(?:default\s+)?)?"
    r"(?:def|class|function|interface|type|struct|enum|fn)\s+([A-Za-z_$][\w$]*)"
)
_SYM_ASSIGN = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[=:]")


def _symbol_outline(text: str, name: str, max_syms: int = 200) -> str | None:
    """큰 파일용 '심볼 지도' — 정의 줄(줄번호+시그니처)만 추려 반환한다. 모델이 이걸 보고
    find_symbol(path, '이름')으로 필요한 심볼만 읽게 유도한다. 심볼이 없으면(코드 아님) None."""
    lines = text.splitlines()
    syms: list[str] = []
    for i, ln in enumerate(lines):
        m = _SYM_DEF.search(ln) or _SYM_ASSIGN.search(ln)
        if not m:
            continue
        sig = ln.strip()
        if len(sig) > 90:
            sig = sig[:90] + "…"
        syms.append(f"{i + 1}\t{sig}")
        if len(syms) >= max_syms:
            syms.append("… (심볼 더 있음)")
            break
    if not syms:
        return None
    return (
        f"파일이 큽니다: {name} ({len(lines)}줄). 전체 대신 심볼 지도를 보여줍니다.\n"
        f"필요한 함수/클래스는 find_symbol(path, '이름')으로, 임의 줄 범위는 "
        f"read_file(path, offset, limit)로 읽으세요.\n\n심볼:\n" + "\n".join(syms)
    )


def _find_symbol_range(text: str, symbol: str, max_lines: int = 200) -> str:
    """파일 텍스트에서 심볼 정의를 찾아 그 범위(줄번호 포함)만 반환한다. tree-sitter 없이
    정규식 + 들여쓰기/최상위 경계로 근사한다(python·js 등 범용). 못 찾으면 안내."""
    if not symbol:
        return "오류: symbol이 필요합니다"
    lines = text.splitlines()
    esc = re.escape(symbol)
    def_pat = re.compile(rf"\b(def|class|function|interface|type|struct|enum|fn)\s+{esc}\b")
    assign_pat = re.compile(rf"\b(const|let|var)\s+{esc}\b|^\s*{esc}\s*[=:]")
    start = None
    for i, ln in enumerate(lines):
        if def_pat.search(ln) or assign_pat.search(ln):
            start = i
            break
    if start is None:
        return f"심볼 '{symbol}'을(를) 찾지 못했습니다. grep으로 검색하거나 read_file로 확인하세요."
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l2 = lines[j]
        if not l2.strip():
            continue
        ind2 = len(l2) - len(l2.lstrip())
        # 같은/더 낮은 들여쓰기에서 새 정의가 나오면 심볼 끝으로 본다.
        if ind2 <= indent and (def_pat.search(l2) or re.search(r"\b(def|class|function)\b", l2) or (ind2 == 0 and l2[0] not in " \t}")):
            end = j
            break
    capped = min(end, start + max_lines)
    numbered = "\n".join(f"{k + 1}\t{lines[k]}" for k in range(start, capped))
    more = f"\n... (심볼이 {end - start}줄 — 전체는 read_file offset={start + 1}) ..." if end - start > max_lines else ""
    return numbered + more


def _is_local_url(url: str) -> bool:
    """로컬 오리진만 허용 — 에이전트가 임의 외부 사이트를 열지 못하게 막는다(SSRF 경계)."""
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = (u.hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


async def _browser_check(url: str, selectors: list[str]) -> str:
    """로컬 웹앱을 headless로 열어 콘솔 에러·uncaught 예외·셀렉터 렌더를 보고한다.
    빌드 통과를 '실제 동작'으로 승격하는 self-repair용. 외부 URL은 거부한다."""
    if not _is_local_url(url):
        return f"[browser_check] 거부 — 로컬 오리진(localhost/127.0.0.1)만 허용됩니다: {url}"
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "[browser_check] playwright 미설치 — 확인 불가"
    page_errors: list[str] = []
    console_errors: list[str] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            try:
                await page.goto(url, wait_until="networkidle", timeout=20000)
                found = {sel: await page.locator(sel).count() for sel in selectors}
            finally:
                await browser.close()
    except Exception as err:
        return f"[browser_check] 로드 실패: {err}"
    lines = [f"[browser_check] {url}"]
    lines.append(f"uncaught 예외: {len(page_errors)}")
    lines += [f"  · {e}" for e in page_errors[:8]]
    # console.error는 SW/PWA 잡음이 섞일 수 있어 참고용으로만 표시한다.
    lines.append(f"console.error: {len(console_errors)} (참고 — SW/PWA 잡음 가능)")
    lines += [f"  · {e}" for e in console_errors[:8]]
    if selectors:
        lines.append("셀렉터 렌더: " + ", ".join(f"{s}={c}" for s, c in found.items()))
        missing = [s for s, c in found.items() if not c]
        if missing:
            lines.append("⚠ 미렌더 셀렉터: " + ", ".join(missing))
    verdict = "정상(로드·uncaught 예외 0)" if not page_errors else "uncaught 예외 발생 — 수정 필요"
    lines.append("판정: " + verdict)
    return "\n".join(lines)


async def execute_tool(name: str, args: dict, workspace: str) -> tuple[str, str]:
    if name == "find_symbol":
        p = _resolve(workspace, str(args["path"]))
        text = await asyncio.to_thread(_read_file_capped, p)
        return _find_symbol_range(text, str(args.get("symbol", ""))), ""
    if name == "read_tool_result":
        from ..runtime import tool_store
        return tool_store.load(str(args.get("result_id", "")),
                               int(args.get("offset", 0) or 0),
                               int(args.get("limit", 4000) or 4000)), ""
    if name == "browser_check":
        url = str(args.get("url") or "http://127.0.0.1:8790")
        sels = args.get("selectors") or []
        if not isinstance(sels, list):
            sels = [str(sels)]
        return await _browser_check(url, [str(s) for s in sels]), ""
    if name == "read_file":
        p = _resolve(workspace, str(args["path"]))
        text = await asyncio.to_thread(_read_file_capped, p)
        offset = args.get("offset")
        limit = args.get("limit")
        if offset or limit:
            # 줄 범위만 읽기 — 큰 파일을 bash sed 대신 read_file로(병렬·무승인).
            lines = text.splitlines()
            start = max(int(offset) - 1, 0) if offset else 0
            end = start + int(limit) if limit else len(lines)
            picked = lines[start:end]
            body = "\n".join(f"{start + i + 1}\t{ln}" for i, ln in enumerate(picked))
            return body, ""
        # 큰 파일을 통째로 읽으면 전체 대신 심볼 지도를 준다 — find_symbol 사용을 유도하고
        # 토큰을 아낀다. 코드가 아니라 심볼이 없으면(None) 기존대로 전체 반환.
        if text.count("\n") + 1 > READ_FILE_OUTLINE_THRESHOLD:
            outline = _symbol_outline(text, Path(str(args["path"])).name)
            if outline:
                return outline, ""
        return text, ""
    if name == "list_dir":
        p = _resolve(workspace, str(args["path"]))
        if p.is_file():
            return await asyncio.to_thread(_read_file_capped, p), ""
        # 동기 재귀라 이벤트 루프를 막는다 — 스레드로 오프로드한다. budget은 _list_tree가
        # 스레드 안에서 monotonic 기준으로 초기화한다(여기서 deadline을 만들면 스레드 시작
        # 지연만큼 시간이 깎인다). capped 여부만 받아 온다.
        budget: dict = {}
        def _run():
            b = {"n": 0, "deadline": __import__("time").monotonic() + _LISTDIR_MAX_SECONDS,
                 "capped": False}
            r = _list_tree(p, 0, b)
            budget["capped"] = b["capped"]
            return r
        lines = await asyncio.to_thread(_run)
        tail = "\n(항목 상한 도달 — 더 좁은 경로로 확인하세요)" if budget.get("capped") else ""
        return ("\n".join(lines) + tail) or "(빈 디렉토리)", ""
    if name == "grep":
        # 모델이 준 path를 존중한다(무시하고 워크스페이스 전체를 훑으면 홈 디렉터리에서 폭주).
        p = _resolve(workspace, str(args.get("path") or "."))
        out: list[str] = []
        # 동기 재귀라 이벤트 루프를 막는다 — 스레드로 오프로드한다.
        await asyncio.to_thread(_grep, p, str(args["pattern"]), args.get("include"), out)
        tail = "\n(결과 상한 도달 — 더 좁은 path/pattern으로 다시 검색하세요)" \
            if len(out) >= _GREP_MAX_HITS else ""
        return ("\n".join(out[:_GREP_MAX_HITS]) + tail) or "검색 결과 없음", ""
    if name == "save_skill":
        import re as _re
        from .. import skills as skills_lib

        raw = str(args.get("name", "")).strip()
        safe = _re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-").lower() or "skill"
        scope = "global" if str(args.get("scope", "")).strip() == "global" else "project"
        path = skills_lib.resolve_path(scope, workspace, raw, safe)  # 경계 밖이면 PermissionError
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(args.get("content", "")), encoding="utf-8")
        return f"skill을 저장했습니다: {safe} ({scope})", ""
    if name == "write_file":
        p = _resolve(workspace, str(args["path"]))
        old_text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        new_text = str(args["content"])
        diff = _make_diff(old_text, new_text, str(p))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_text, encoding="utf-8")
        return f"{WRITE_OK_PREFIX}: {p}", diff
    if name == "edit_file":
        p = _resolve(workspace, str(args["path"]))
        old = str(args["old_string"])
        new = str(args["new_string"])
        content = p.read_text(encoding="utf-8", errors="replace")
        if old not in content:
            raise ValueError(f"old_string을 파일에서 찾을 수 없습니다: {p}")
        new_content = content.replace(old, new, 1)
        diff = _make_diff(content, new_content, str(p))
        p.write_text(new_content, encoding="utf-8")
        return f"파일을 수정했습니다: {p}", diff
    if name == "build_frontend":
        import shutil
        fe = Path(workspace) / "frontend"
        if not (fe / "package.json").is_file():
            return "frontend/package.json이 없어 빌드할 수 없습니다.", ""
        npm = shutil.which("npm")
        if not npm:
            return "host에 npm이 없어 빌드할 수 없습니다.", ""
        proc = await asyncio.create_subprocess_exec(
            npm, "run", "build", cwd=str(fe),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        tail = out.decode(errors="replace")[-1500:]
        head = "빌드 성공\n" if proc.returncode == 0 else f"빌드 실패(exit {proc.returncode})\n"
        return head + tail, ""
    if name == "bash":
        command = str(args["command"])
        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                raise PermissionError(f"차단된 명령입니다: {blocked}")
        from ..sandbox.executor import DockerSandbox

        # workspace를 명시 전달 — 미전달 시 전역 settings.workspace로 실행돼 방 경계를 벗어난다.
        return await DockerSandbox(workspace=workspace).run(command, write=True), ""
    raise ValueError(f"알 수 없는 도구: {name}")
