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

    # ── 신뢰성 지표 산식 회귀 고정: FORGE 완료 주장 × deterministic checker confusion matrix ──
    from bench import aggregate
    agg = aggregate([
        {"code": "T", "success": True, "cost": 0.01, "elapsed_s": 5.0, "forge_status": "completed"},
        {"code": "T", "success": False, "cost": 0.02, "elapsed_s": 6.0, "forge_status": "completed"},
        {"code": "T", "success": True, "cost": 0.03, "elapsed_s": 7.0, "forge_status": "verification_failed"},
        {"code": "T", "success": True, "cost": 0.04, "elapsed_s": 8.0, "forge_status": "completed_unverified"},
    ])["overall"]
    assert agg["verified_success_rate"] == 0.5, agg          # completed+checker / total
    assert agg["false_completion_rate"] == 0.25, agg          # completed인데 checker 실패(최악)
    assert agg["false_failure_rate"] == 0.25, agg             # verification_failed인데 checker 성공
    assert abs(agg["cost_per_verified_task"] - 0.05) < 1e-9, agg  # 0.10 / verified 2
    assert aggregate([{"code": "Z", "success": False, "cost": 0.1, "elapsed_s": 1.0,
                       "forge_status": "verification_failed"}])["overall"]["cost_per_verified_task"] is None
    print("benchmark 신뢰성 지표: OK — verified/false_completion/cost_per_verified 산식 고정")

    print(f"benchmark 품질 테스트 통과 ✓ (task {len(TASKS)} · 카테고리 {len(cats)} · COMPLEX {n_complex} · 정답 노출 없음)")


if __name__ == "__main__":
    main()
