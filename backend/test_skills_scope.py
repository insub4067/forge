"""3계층 skill scope 검증 — Curated + Learned + Project (spec §12)."""
import tempfile
from pathlib import Path
from unittest import mock

from app import skills as S
from app.runtime import agent as A


def _mk(base, name, body="x"):
    p = Path(base) / ".forge" / "skills"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{name}.md").write_text(body, encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as curated, tempfile.TemporaryDirectory() as home, \
         tempfile.TemporaryDirectory() as ws1, tempfile.TemporaryDirectory() as ws2:
        cdir = Path(curated)
        ldir = Path(home) / ".forge" / "skills"
        ldir.mkdir(parents=True)
        with mock.patch.object(S, "CURATED_DIR", cdir), \
             mock.patch.object(S, "LEARNED_DIR", ldir):
            # curated(번들)
            (cdir / "minimal-implementation.md").write_text("YAGNI 사다리 debug fastapi", encoding="utf-8")
            (cdir / "README.md").write_text("인덱스", encoding="utf-8")  # 제외돼야
            # learned(홈 global)
            (ldir / "git-recovery.md").write_text("reflog로 복구 git", encoding="utf-8")
            # project
            _mk(ws1, "frontend-build", "이 프로젝트 빌드 절차 build")
            _mk(ws1, "git-recovery", "ws1 전용 git 절차")  # learned와 이름 충돌 → project 우선
            _mk(ws2, "trade-strategy", "ws2 전략")

            n1 = {s["name"]: s for s in S.iter_skills(ws1)}
            n2 = {s["name"]: s for s in S.iter_skills(ws2)}

            # README 제외
            assert "readme" not in [k.lower() for k in n1], "README 제외"
            # curated는 모든 ws에서 보인다
            assert "minimal-implementation" in n1 and "minimal-implementation" in n2, "curated 가시성"
            assert n1["minimal-implementation"]["origin"] == "curated", "curated origin"
            assert n1["minimal-implementation"]["scope"] == "global", "curated scope=global"
            # learned도 모든 ws에서 보인다(ws2는 충돌 없음 → learned 그대로)
            assert n2["git-recovery"]["origin"] == "learned", "learned origin"
            # project skill은 다른 ws에서 안 보인다
            assert "frontend-build" in n1 and "frontend-build" not in n2, "project 격리"
            assert "trade-strategy" in n2 and "trade-strategy" not in n1, "project 격리2"
            # 우선순위: 같은 이름이면 project > learned
            assert n1["git-recovery"]["content"] == "ws1 전용 git 절차", "project override 내용"
            assert n1["git-recovery"]["scope"] == "project", "project override scope"
            assert n1["git-recovery"]["origin"] == "project", "project override origin"
            # 재귀 미수집: 상위 디렉터리를 ws로 잡아도 하위 프로젝트 skill 안 걸림
            desktop = str(Path(ws1).parent)
            assert "frontend-build" not in {s["name"] for s in S.iter_skills(desktop)}, "재귀 미수집"

            # save 경로: global → learned, project → workspace. curated엔 안 쓴다.
            gp = S.resolve_path("global", ws1, "x", "x")
            assert str(gp).startswith(str(ldir.resolve())), "global write는 learned로"
            assert not str(gp).startswith(str(cdir.resolve())), "curated엔 안 씀"
            pp = S.resolve_path("project", ws1, "x", "x")
            assert str(pp).startswith(str((Path(ws1) / ".forge" / "skills").resolve())), "project write는 workspace로"
            # 경계/traversal 차단
            try:
                S.resolve_path("global", ws1, "x", "../../etc/passwd")
                raise AssertionError("traversal 통과됨")
            except PermissionError:
                pass

            # selective retrieval: 관련 skill만, MAX_ACTIVE_SKILLS·SKILL_CHAR_BUDGET 준수
            sel = A._select_skills(ws1, "git 되돌리기 복구")
            assert "git-recovery" in sel, "관련 skill 선택"
            assert "frontend-build" not in sel, "무관 skill 제외"
            assert "trade-strategy" not in sel, "다른 ws skill 제외"
            # 관련 없는 질의는 빈 문자열
            assert A._select_skills(ws1, "날씨 어때") == "" or "git" not in A._select_skills(ws1, "날씨 어때"), "무관 질의"
            # cap: 후보를 많이 만들어도 MAX_ACTIVE_SKILLS 초과 안 함
            for i in range(10):
                _mk(ws1, f"debughelper{i}", "debug 절차 " * 5)
            sel2 = A._select_skills(ws1, "debug")
            assert sel2.count("### skill:") <= A.MAX_ACTIVE_SKILLS, f"MAX_ACTIVE 초과: {sel2.count('### skill:')}"
            assert len(sel2) <= A.SKILL_CHAR_BUDGET + 200, "CHAR_BUDGET 대략 준수"

            print("3계층 skill scope 테스트 통과 ✓ (curated/learned/project · 우선순위 · 경계 · selective cap)")


if __name__ == "__main__":
    main()
