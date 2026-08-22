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
]


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


async def execute_tool(name: str, args: dict, workspace: str) -> str:
    if name == "read_file":
        p = _resolve(workspace, str(args["path"]))
        return p.read_text(encoding="utf-8", errors="replace")
    if name == "list_dir":
        p = _resolve(workspace, str(args["path"]))
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        lines = _list_tree(p, 0)
        return "\n".join(lines) or "(빈 디렉토리)"
    if name == "grep":
        p = _resolve(workspace, ".")
        out: list[str] = []
        _grep(p, str(args["pattern"]), args.get("include"), out)
        return "\n".join(out[:100]) or "검색 결과 없음"
    raise ValueError(f"알 수 없는 도구: {name}")
