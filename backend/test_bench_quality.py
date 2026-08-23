"""benchmark 자체의 품질 검증 (지침 §2) — benchmark가 FORGE에 유리하게 만들어지지 않게.

검사: 정답 노출, task 다양성, trivial 비중, 중복, checker 유효성, 상태 오염.
LLM 없음, 무비용.
"""
import tempfile
from pathlib import Path

from bench_tasks import TASKS


def main():
    codes = [t["code"] for t in TASKS]
    # 1) task 수·중복
    assert len(TASKS) >= 20, f"task가 20개 미만: {len(TASKS)}"
    assert len(codes) == len(set(codes)), f"중복 code: {codes}"

    # 2) 카테고리 다양성 — trivial 편중 방지
    cats = {t["category"] for t in TASKS}
    assert len(cats) >= 12, f"카테고리 다양성 부족: {len(cats)}"

    # 3) COMPLEX task 충분(planner 실험용)
    n_complex = sum(1 for t in TASKS if t.get("complex"))
    assert n_complex >= 4, f"COMPLEX task 부족: {n_complex}"

    # 4) 정답 노출 방지 — prompt에 fix의 로직 라인(def/return/class/raise)이 그대로 들어가면 안 된다.
    #    (내용/설정 리터럴은 스펙이므로 허용 — 로직 라인만 검사)
    LOGIC = ("def ", "return ", "class ", "raise ")
    for t in TASKS:
        if t.get("already_ok"):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            t["setup"](d)
            t["fix"](d)
            leaked = []
            for p in d.rglob("*"):
                if not p.is_file():
                    continue
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    s = line.strip()
                    if len(s) >= 12 and any(s.startswith(k) for k in LOGIC) and s in t["prompt"]:
                        leaked.append((t["code"], s))
            assert not leaked, f"prompt에 정답 로직 노출: {leaked}"

    # 5) checker 유효성 — 모든 task는 setup/check/fix(또는 break_it)를 갖춘다.
    for t in TASKS:
        assert callable(t["setup"]) and callable(t["check"]), t["code"]
        if t.get("already_ok"):
            assert callable(t.get("break_it")), f"{t['code']} already_ok인데 break_it 없음"
        else:
            assert callable(t.get("fix")), f"{t['code']} fix 없음"

    # 6) 상태 오염 방지 — 각 task는 setup에서 자기 fixture만 만든다(격리는 tmpdir로 보장).
    #    두 task를 같은 dir에 순서대로 setup해도 서로의 checker에 영향 없어야 한다(파일명 충돌 시 감지).
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # 대표로 몇 개를 겹쳐 setup — check가 예외 없이 동작(오염으로 크래시 안 함)
        for t in TASKS[:5]:
            t["setup"](d)
        for t in TASKS[:5]:
            try:
                t["check"](d)  # 예외만 안 나면 OK(결과값은 무관)
            except Exception as e:
                raise AssertionError(f"{t['code']} checker가 오염 상태에서 크래시: {e}")

    print(f"benchmark 품질 테스트 통과 ✓ (task {len(TASKS)} · 카테고리 {len(cats)} · COMPLEX {n_complex} · 정답 노출 없음)")


if __name__ == "__main__":
    main()
