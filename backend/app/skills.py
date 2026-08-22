"""Skill scope — Global(~/.forge/skills) + Workspace(<ws>/.forge/skills) 2-tier.

재귀 탐색은 하지 않는다(하위 프로젝트 skill 무차별 수집 금지). 두 디렉터리만 병합하고,
같은 이름이면 Workspace가 Global을 override한다. path traversal/symlink escape는
resolve_path에서 차단한다(특히 Global write는 모든 workspace에 영향 → 경계 필수).
"""
from pathlib import Path

GLOBAL_SKILLS_DIR = Path.home() / ".forge" / "skills"


def _scope_dir(scope: str, workspace: str) -> Path:
    if scope == "global":
        return GLOBAL_SKILLS_DIR
    return Path(workspace) / ".forge" / "skills"


def iter_skills(workspace: str) -> list[dict]:
    """global→workspace 순으로 병합(같은 이름은 workspace 우선). 각 항목에 scope 포함."""
    merged: dict[str, dict] = {}
    for scope in ("global", "workspace"):
        sdir = _scope_dir(scope, workspace)
        if not sdir.is_dir():
            continue
        for p in sorted(sdir.glob("*.md")):
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue
            merged[p.stem] = {
                "name": p.stem,
                "content": content,
                "scope": scope,
                "path": str(p),
                "mtime": int(p.stat().st_mtime),
            }
    return [merged[k] for k in sorted(merged)]


def resolve_path(scope: str, workspace: str, name: str, safe_name: str) -> Path:
    """scope 디렉터리 안의 <safe_name>.md 경로. 경계 밖(symlink 포함)이면 PermissionError."""
    root = _scope_dir(scope, workspace).resolve()
    p = (root / f"{safe_name}.md").resolve()
    if p != root and root not in p.parents:
        raise PermissionError(f"skill 경계 밖 경로: {name}")
    return p
