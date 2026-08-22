from pathlib import Path

from ..config import settings

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's contents. Returns the file text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative path"}
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
]

# chat 에이전트는 읽기·질문만 — 코드 수정/실행 도구는 제외한다.
CHAT_TOOLS = [
    t for t in TOOL_SCHEMAS
    if t["function"]["name"] in {"read_file", "list_dir", "grep", "ask_user"}
]

APPROVAL_REQUIRED = {"write_file", "edit_file", "bash"}
BLOCKED_COMMANDS = ["rm -rf", "git push", "sudo ", "chmod 777"]


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
        return p.read_text(encoding="utf-8", errors="replace"), ""
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
    if name == "bash":
        command = str(args["command"])
        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                raise PermissionError(f"차단된 명령입니다: {blocked}")
        from ..sandbox.executor import DockerSandbox

        return await DockerSandbox().run(command, write=True), ""
    raise ValueError(f"알 수 없는 도구: {name}")
