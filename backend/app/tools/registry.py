from pathlib import Path

from ..config import settings

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file's contents. Returns the file text with line numbers. "
                "For large files, pass offset/limit to read only a line range "
                "instead of running bash sed/cat — this is faster (parallel, no approval)."
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
                                    "enum": ["todo", "planning", "in_progress", "review", "debug", "done"],
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
]

# chat 에이전트는 읽기·질문만 — 코드 수정/실행 도구는 제외한다.
CHAT_TOOLS = [
    t for t in TOOL_SCHEMAS
    if t["function"]["name"] in {"read_file", "list_dir", "grep", "ask_user"}
]

# build_frontend는 host에서 npm run build를 직접 실행(Docker 우회) — 승인 필요.
APPROVAL_REQUIRED = {"write_file", "edit_file", "bash", "save_skill", "build_frontend"}
# host 모드에서 bash가 호스트에 직접 닿으므로, FORGE를 실행 중인 백엔드 프로세스를
# 스스로 죽이는 것을 막는다(자기 세션 자멸·완전 다운 방지). 백엔드 변경 적용을 위한
# 재시작은 FORGE가 아니라 사람이/슈퍼바이저가 한다. 빌드는 build_frontend 도구를 쓴다.
BLOCKED_COMMANDS = ["rm -rf", "git push", "sudo ", "chmod 777",
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


def _list_tree(path: Path, depth: int) -> list[str]:
    lines: list[str] = []
    try:
        entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name))
    except PermissionError:
        return [f"{'  ' * depth}? (접근 불가)"]
    for e in entries:
        if e.name in {"node_modules", ".git", "__pycache__", ".venv"}:
            continue
        if e.is_dir():
            lines.append(f"{'  ' * depth}{e.name}/")
            if depth < 2:
                lines.extend(_list_tree(e, depth + 1))
        else:
            lines.append(f"{'  ' * depth}{e.name}")
    return lines


def _grep(path: Path, pattern: str, include: str | None, out: list[str]) -> None:
    import re

    regex = re.compile(pattern)
    try:
        entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name))
    except PermissionError:
        return
    for e in entries:
        if e.name in {"node_modules", ".git", "__pycache__", ".venv"}:
            continue
        if e.is_dir():
            _grep(e, pattern, include, out)
            continue
        if include and not e.match(include):
            continue
        try:
            text = e.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                out.append(f"{e}:{i}: {line.strip()}")


def _make_diff(old_text: str, new_text: str, path: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


async def execute_tool(name: str, args: dict, workspace: str) -> tuple[str, str]:
    if name == "read_file":
        p = _resolve(workspace, str(args["path"]))
        text = p.read_text(encoding="utf-8", errors="replace")
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
        return text, ""
    if name == "list_dir":
        p = _resolve(workspace, str(args["path"]))
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace"), ""
        lines = _list_tree(p, 0)
        return "\n".join(lines) or "(빈 디렉토리)", ""
    if name == "grep":
        p = _resolve(workspace, ".")
        out: list[str] = []
        _grep(p, str(args["pattern"]), args.get("include"), out)
        return "\n".join(out[:100]) or "검색 결과 없음", ""
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
        return f"파일을 작성했습니다: {p}", diff
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
        import asyncio
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
