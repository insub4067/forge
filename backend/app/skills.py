"""Skill scope — 3계층: Curated(번들) + Learned(~/.forge/skills) + Project(<ws>/.forge/skills).

- Curated: FORGE에 번들되어 배포되는 검증된 범용 방법론(레포 안 → 버전관리·fresh install 즉시 사용).
- Learned: FORGE가 작업 중 save_skill(scope="global")로 축적한 범용 절차(사용자 홈, 여러 workspace 공유).
- Project: 해당 workspace 전용(기존 방식 그대로).

재귀 탐색은 하지 않는다(하위 프로젝트 skill 무차별 수집 금지). 정해진 디렉터리만 읽는다.
이름 충돌 우선순위: Project > Learned > Curated(명시적 local 규칙이 범용보다 우선).
path traversal/symlink escape는 resolve_path에서 차단한다(특히 global write는 모든 workspace에 영향).
"""
from pathlib import Path

CURATED_DIR = Path(__file__).resolve().parent / "curated_skills"     # 레포 번들(읽기 전용)
LEARNED_DIR = Path.home() / ".forge" / "skills"                       # 사용자 홈(save global 대상)
# 하위호환 별칭 — 기존 코드/테스트가 참조하던 이름. global write는 여기(=learned)로 간다.
GLOBAL_SKILLS_DIR = LEARNED_DIR


def _workspace_dir(workspace: str) -> Path:
    return Path(workspace) / ".forge" / "skills"


def _sources(workspace: str) -> list[tuple[str, str, Path]]:
    """(scope, origin, dir) 목록. 뒤에 오는 것이 이름 충돌 시 우선(override)."""
    return [
        ("global", "curated", CURATED_DIR),
        ("global", "learned", LEARNED_DIR),
        ("project", "project", _workspace_dir(workspace)),
    ]


def iter_skills(workspace: str) -> list[dict]:
    """curated→learned→project 순 병합(같은 이름은 뒤가 우선 = project > learned > curated).
    각 항목에 scope(project|global)와 origin(curated|learned|project)을 담는다."""
    merged: dict[str, dict] = {}
    for scope, origin, sdir in _sources(workspace):
        if not sdir.is_dir():
            continue
        for p in sorted(sdir.glob("*.md")):
            if p.stem.lower() == "readme":  # 인덱스 파일 — skill 아님, 주입 제외
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue
            merged[p.stem] = {
                "name": p.stem,
                "content": content,
                "scope": scope,
                "origin": origin,
                "path": str(p),
                "mtime": int(p.stat().st_mtime),
            }
    return [merged[k] for k in sorted(merged)]


def resolve_path(scope: str, workspace: str, name: str, safe_name: str) -> Path:
    """저장 대상 경로. global은 learned(~/.forge/skills)로 간다 — curated(번들)엔 쓰지 않는다.
    경계 밖(symlink 포함)이면 PermissionError."""
    root = (LEARNED_DIR if scope == "global" else _workspace_dir(workspace)).resolve()
    p = (root / f"{safe_name}.md").resolve()
    if p != root and root not in p.parents:
        raise PermissionError(f"skill 경계 밖 경로: {name}")
    return p
