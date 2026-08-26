"""Reviewer 검출력 측정 (R 시리즈) — 외부 리뷰 P1-F.

문제의식: test_reviewer_capability는 Reviewer의 '도구 격리'(read-only)만 검증한다. Reviewer가
결함을 실제로 잡아내는 비율(검출력)은 어디에서도 재지 않는다. 검출력이 낮은 리뷰 단계는 비용·
지연만 쓰면서 '리뷰를 거쳤다'는 잘못된 신뢰를 만든다 — 없느니만 못하다.

이 도구는 gate_eval.py(F 시리즈)의 방식을 Reviewer에 이식한다: 알려진 결함이 심긴 변경(diff)을
Reviewer에 넣고, PASS/FAIL 판정으로 **검출률(defect→FAIL)**과 **오탐률(clean→FAIL)**을 잰다.

  python reviewer_eval.py --self-test   # 픽스처·채점 로직 검증(무료, LLM 없음)
  python reviewer_eval.py --run [--tier auto]  # 실제 Reviewer 호출(LLM 비용 발생)

각 케이스: base 코드를 커밋한 git 워크스페이스에 변경을 uncommitted로 적용 → Reviewer가 git diff로
독립 검증 → 마지막 줄 PASS / FAIL 로 판정(reviewer.md 규약). should_flag=True면 FAIL이 정답.
"""
import argparse
import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class RCase:
    cid: str
    kind: str           # defect 유형 또는 'clean'
    goal: str           # 사용자 요청
    plan: str           # 완료 조건
    path: str           # 변경 파일 경로
    base: str           # 변경 전 코드(커밋됨)
    changed: str        # 변경 후 코드(uncommitted diff)
    should_flag: bool   # 결함이면 True(Reviewer가 FAIL 내야 정답), clean이면 False


# ── R 시리즈: 결함 주입 + clean 대조 ─────────────────────────────────────
CASES: list[RCase] = [
    RCase("R1", "off-by-one", "리스트 마지막 요소까지 합산하는 sum_to 구현",
          "sum_to(n)는 0..n-1 합을 반환(끝 배타)", "calc.py",
          "def sum_to(n):\n    return sum(range(n))\n",
          "def sum_to(n):\n    return sum(range(n + 1))\n", True),  # 끝 포함으로 바뀜(off-by-one)
    RCase("R2", "none-deref", "user dict에서 name을 대문자로", "user가 None이면 빈 문자열",
          "svc.py",
          "def uname(user):\n    if not user:\n        return ''\n    return user['name'].upper()\n",
          "def uname(user):\n    return user['name'].upper()\n", True),  # None 가드 제거
    RCase("R3", "wrong-op", "잔액에서 금액 차감", "balance - amount",
          "acct.py",
          "def debit(balance, amount):\n    return balance - amount\n",
          "def debit(balance, amount):\n    return balance + amount\n", True),  # 부호 뒤집힘
    RCase("R4", "resource-leak", "파일 읽어 반환", "with로 파일을 확실히 닫는다",
          "io_util.py",
          "def read_all(p):\n    with open(p) as f:\n        return f.read()\n",
          "def read_all(p):\n    f = open(p)\n    return f.read()\n", True),  # 파일 안 닫힘
    RCase("R5", "mutable-default", "항목 추가 헬퍼", "호출 간 상태 공유 금지",
          "acc.py",
          "def add(x, items=None):\n    items = items or []\n    items.append(x)\n    return items\n",
          "def add(x, items=[]):\n    items.append(x)\n    return items\n", True),  # mutable default arg
    RCase("R6", "logic-inversion", "짝수만 통과시키는 필터", "n이 짝수면 True",
          "flt.py",
          "def is_even(n):\n    return n % 2 == 0\n",
          "def is_even(n):\n    return n % 2 != 0\n", True),  # 홀수를 통과(반전)
    RCase("R7", "clean-refactor", "합계 함수 가독성 개선", "동작 불변, total 반환",
          "sums.py",
          "def total(xs):\n    t = 0\n    for x in xs:\n        t = t + x\n    return t\n",
          "def total(xs):\n    return sum(xs)\n", False),  # 동작 보존 리팩터 — PASS가 정답
    RCase("R8", "clean-feature", "리스트 평균 추가(빈 리스트 0)", "mean([])==0, 정상 평균",
          "stat.py",
          "def mean(xs):\n    return 0\n",
          "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n", False),  # 올바른 구현 — PASS가 정답
]


def _git(ws, *args):
    return subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True, timeout=30)


def setup_workspace(c: RCase) -> str:
    """base를 커밋한 git 워크스페이스에 changed를 uncommitted로 적용. 워크스페이스 경로 반환."""
    ws = tempfile.mkdtemp(prefix=f"reveval-{c.cid}-")
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "eval@forge")
    _git(ws, "config", "user.name", "eval")
    fp = os.path.join(ws, c.path)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(c.base)
    _git(ws, "add", ".")
    _git(ws, "commit", "-qm", "base")
    with open(fp, "w", encoding="utf-8") as f:   # 이번 '작업'의 변경(uncommitted diff)
        f.write(c.changed)
    return ws


def _verdict_from_text(text: str) -> str:
    """reviewer.md 규약: 마지막 유의미한 줄이 PASS 또는 FAIL:로 시작. 없으면 'unknown'."""
    for line in reversed([ln.strip() for ln in (text or "").splitlines() if ln.strip()]):
        up = line.upper()
        if up.startswith("PASS"):
            return "PASS"
        if up.startswith("FAIL"):
            return "FAIL"
    return "unknown"


async def _review_one(rt, c: RCase, send) -> str:
    """워크스페이스를 만들고 Reviewer를 호출해 PASS/FAIL을 얻는다. LLM 호출(비용)."""
    from app.runtime.prompts import _reviewer_context, _last_assistant_text
    from app.tools.registry import TOOL_SCHEMAS
    from app.runtime.agent import READ_ONLY_TOOLS
    ws = setup_workspace(c)
    ro_tools = [t for t in TOOL_SCHEMAS if t["function"]["name"] in READ_ONLY_TOOLS]
    msgs = _reviewer_context([{"role": "user", "content": c.goal}], c.plan)
    await rt._run_role("reviewer", msgs, send, "", ws, {"goal": c.goal, "files_changed": [], "errors": []},
                       [], 0, tools=ro_tools, plan=c.plan, persist=False)
    return _verdict_from_text(_last_assistant_text(msgs))


def score(verdicts: list[tuple]) -> dict:
    """verdicts: [(RCase, verdict)]. 검출률·오탐률·정확도."""
    defects = [(c, v) for c, v in verdicts if c.should_flag]
    cleans = [(c, v) for c, v in verdicts if not c.should_flag]
    detected = sum(1 for c, v in defects if v == "FAIL")
    false_pos = sum(1 for c, v in cleans if v == "FAIL")
    correct = detected + sum(1 for c, v in cleans if v == "PASS")
    return {
        "detection_rate": round(detected / len(defects), 3) if defects else None,
        "false_positive_rate": round(false_pos / len(cleans), 3) if cleans else None,
        "accuracy": round(correct / len(verdicts), 3) if verdicts else None,
        "n_defect": len(defects), "n_clean": len(cleans),
    }


async def run_eval(tier: str = "auto") -> dict:
    from app.runtime.agent import AgentRuntime
    rt = AgentRuntime()

    async def send(_t, _d):
        return None

    verdicts = []
    for c in CASES:
        try:
            v = await _review_one(rt, c, send)
        except Exception as err:  # noqa: BLE001
            v = f"error:{err}"
        verdicts.append((c, v))
        print(f"{c.cid} [{c.kind}] should_flag={c.should_flag} → {v}")
    s = score([(c, v) for c, v in verdicts])
    print("\n검출률(defect→FAIL):", s["detection_rate"],
          "| 오탐률(clean→FAIL):", s["false_positive_rate"], "| 정확도:", s["accuracy"])
    print("판단: 검출률이 낮으면(예 <0.5) Reviewer 존치는 비용·지연만 쓰는 잘못된 신뢰 — 승급 또는 제거 검토.")
    return s


def _self_test():
    """LLM 없이 픽스처·워크스페이스·판정 파서를 검증한다."""
    # 파서
    assert _verdict_from_text("설명\nFAIL: off-by-one") == "FAIL"
    assert _verdict_from_text("좋음\nPASS") == "PASS"
    assert _verdict_from_text("모호") == "unknown"
    # 채점 로직
    s = score([(CASES[0], "FAIL"), (CASES[6], "PASS")])   # R1 defect 검출, R7 clean 통과
    assert s["detection_rate"] == 1.0 and s["false_positive_rate"] == 0.0 and s["accuracy"] == 1.0
    s2 = score([(CASES[0], "PASS"), (CASES[6], "FAIL")])  # 놓침 + 오탐
    assert s2["detection_rate"] == 0.0 and s2["false_positive_rate"] == 1.0
    # 픽스처: base≠changed, should_flag 정의, git diff 실제 생성
    codes = set()
    for c in CASES:
        assert c.base != c.changed, f"{c.cid}: base==changed"
        assert isinstance(c.should_flag, bool)
        codes.add(c.cid)
        ws = setup_workspace(c)
        diff = _git(ws, "diff").stdout
        assert diff.strip(), f"{c.cid}: git diff가 비어 있음"
    assert len(codes) == len(CASES), "중복 case_id"
    assert sum(1 for c in CASES if c.should_flag) >= 4 and sum(1 for c in CASES if not c.should_flag) >= 2
    print(f"reviewer_eval self-test 통과 ✓ (R 시리즈 {len(CASES)}케이스: "
          f"defect {sum(1 for c in CASES if c.should_flag)} + clean {sum(1 for c in CASES if not c.should_flag)}, "
          "파서·채점·픽스처 검증)")


def main():
    ap = argparse.ArgumentParser(description="Reviewer 검출력 측정 (R 시리즈, P1-F)")
    ap.add_argument("--self-test", action="store_true", help="픽스처·채점 검증(무료)")
    ap.add_argument("--run", action="store_true", help="실제 Reviewer 호출(LLM 비용)")
    ap.add_argument("--tier", default="auto")
    args = ap.parse_args()
    if args.run:
        asyncio.run(run_eval(args.tier))
    else:
        _self_test()


if __name__ == "__main__":
    main()
