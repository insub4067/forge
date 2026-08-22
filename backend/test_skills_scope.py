"""Global+Workspace skill scope 검증 — proposal §16 테스트 항목."""
import tempfile, os
from pathlib import Path
from unittest import mock

from app import skills as S


def _mk(d, name, body="x"):
    p = Path(d) / ".forge" / "skills"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{name}.md").write_text(body, encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as ws1, tempfile.TemporaryDirectory() as ws2:
        gdir = Path(home) / ".forge" / "skills"
        with mock.patch.object(S, "GLOBAL_SKILLS_DIR", gdir):
            _mk(home, "git-recovery", "global git")   # global
            _mk(ws1, "frontend-build", "ws1 build")   # ws1 only
            _mk(ws1, "git-recovery", "ws1 override")  # 같은 이름 override
            _mk(ws2, "trade-strategy", "ws2 only")

            n1 = {s["name"]: s for s in S.iter_skills(ws1)}
            n2 = {s["name"]: s for s in S.iter_skills(ws2)}

            # 1) global이 모든 ws에서 보인다
            assert "git-recovery" in n1 and "git-recovery" in n2, "global 가시성"
            # 2) workspace skill은 다른 ws에서 안 보인다
            assert "frontend-build" in n1 and "frontend-build" not in n2, "ws 격리"
            assert "trade-strategy" in n2 and "trade-strategy" not in n1, "ws 격리2"
            # 3) 같은 이름이면 workspace override
            assert n1["git-recovery"]["content"] == "ws1 override", "override 내용"
            assert n1["git-recovery"]["scope"] == "workspace", "override scope"
            # ws2엔 override 없으니 global 그대로
            assert n2["git-recovery"]["scope"] == "global", "미override scope"
            # 4) 재귀 수집 안 함 — Desktop(상위) 아래 하위프로젝트 skill 무시
            desktop = Path(ws1).parent  # 상위 디렉터리
            # ws1은 desktop 아래 하위. desktop을 ws로 잡아도 ws1의 skill은 안 걸린다
            names_desktop = {s["name"] for s in S.iter_skills(str(desktop))}
            assert "frontend-build" not in names_desktop, "재귀 미수집"

            # 6/7) 경계: global write가 ~/.forge/skills 밖으로 못 나간다
            ok = S.resolve_path("global", ws1, "safe", "safe")
            assert str(ok).startswith(str(gdir.resolve())), "global 정상경로"
            try:
                S.resolve_path("global", ws1, "../evil", "../evil")  # safe_name엔 이미 정규화되지만 방어 확인
                # safe_name은 호출부에서 정규화되나, 직접 traversal 시도가 막히는지
                bad = S.resolve_path("global", ws1, "x", "../../etc/passwd")
                raise AssertionError("traversal 통과됨")
            except PermissionError:
                pass
            print("skill scope 테스트 통과 ✓ (global 가시성/ws 격리/override/재귀미수집/경계)")


if __name__ == "__main__":
    main()
