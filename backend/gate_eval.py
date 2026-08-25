"""Acceptance Gate 오판 평가 장치 — Gate의 '완료 판정' 정확도를 실패 유형별로 측정한다.

FORGE의 핵심 품질은 에이전트의 답변이 아니라 Gate의 완료 판정 정확도다. 이 장치는 8개
실패 유형별 결정적 fixture를 **실제 Gate 판정 로직**(agent._verify_gates / clamp /
resolve_completion_verification)에 넣어 false PASS / false FAIL을 측정한다. LLM·네트워크는
쓰지 않는다.

중요: 현재 Gate가 구조적으로 잡을 수 있는 유형(detectable=True)과, 지금 판정 체계로는
잡지 못하는 유형(detectable=False, 잠재적 false PASS 리스크)을 **정직하게 구분**한다.
잡지 못하는 유형을 통과처럼 숨기지 않는다 — 이것이 '오판 측정'의 목적이다.

기존 R0 벤치마크(bench.py)와는 측정 대상이 다르므로(작업 성공률 vs 판정 정확도) 억지로
합치지 않고 별도 장치로 둔다.

실행(리포트): python gate_eval.py
테스트(회귀): python -m pytest test_gate_eval.py -q
"""
import asyncio
import tempfile
import time
from dataclasses import dataclass, field

from app.runtime import agent as A


# ── 실제 Gate 로직을 호출하는 얇은 러너 (test_acceptance_gates와 동일 패턴) ──
async def _run_verify_gates(gates: list[dict]) -> tuple[str, str, list]:
    """실제 _verify_gates를 tempdir 샌드박스에서 실행. store는 in-memory mock."""
    rt = A.AgentRuntime()
    saved: list = []

    async def fake_list(sid):
        return [dict(g) for g in gates]

    async def fake_save(sid, gid, status, evidence, reason):
        saved.append((gid, status, evidence, reason))
        for g in gates:
            if g["id"] == gid:
                g["status"] = status

    _orig_list, _orig_save = A.store.list_gates, A.store.save_gate_result
    A.store.list_gates, A.store.save_gate_result = fake_list, fake_save

    async def send(event_type, data):
        pass

    try:
        with tempfile.TemporaryDirectory() as d:
            state, report = await rt._verify_gates(d, "s1", send)
    finally:
        A.store.list_gates, A.store.save_gate_result = _orig_list, _orig_save
    return state, report, saved


def _gate(gid, title, method, expected, status="working"):
    return {"id": gid, "title": title, "verification_method": method,
            "expected_result": expected, "status": status, "failure_reason": None}


# ── 평가 결과 모델 ──
@dataclass
class EvalResult:
    case_id: str          # F1..F8
    failure_type: str     # 실패 유형(한글)
    task: str             # 입력 작업
    expected: str         # 기대 판정
    actual: str           # 실제 판정
    basis: str            # 판정 근거(증거)
    detectable: bool      # 현재 Gate가 구조적으로 판정 가능한가
    false_pass: bool = False  # 실패인데 통과(가장 위험)
    false_fail: bool = False  # 정상인데 실패
    elapsed_ms: int = 0


# 각 케이스: (case_id, 유형, task, detectable, coro-factory)
# coro-factory는 (expected, actual, basis, false_pass, false_fail)를 반환.


async def case_f1_test_fail():
    # 테스트가 실패(exit≠0)했는데 gate가 통과로 판정하는가.
    st, rep, saved = await _run_verify_gates([_gate(1, "단위테스트", "exit 1", "OK")])
    expected, actual = "failed", st
    fp = actual == "passed"
    return expected, actual, f"gate 재실행 exit≠0 → {actual}; evidence={saved and saved[0][2][:60]}", fp, False


async def case_f2_build_fail():
    # 빌드가 실패했는데 통과로 판정하는가.
    st, rep, saved = await _run_verify_gates([_gate(1, "빌드", "sh -c 'echo BUILD_FAIL; exit 2'", "built ok")])
    expected, actual = "failed", st
    fp = actual == "passed"
    return expected, actual, f"빌드 exit 2 → {actual}", fp, False


async def case_f3_partial_requirement():
    # 요구사항 2개 중 1개만 검증되고 1개는 검증불가 → 완전 완료(completed)로 둔갑하는가.
    st, rep, _ = await _run_verify_gates([
        _gate(1, "로그인", "echo ok", "ok"),          # passed
        _gate(2, "회원가입", "", ""),                  # unavailable (검증 방법 없음)
    ])
    final = A.resolve_completion_verification(st, "passed")
    expected, actual = "completed_unverified", final
    fp = actual == "completed"   # 일부 미검증인데 완전 완료면 false PASS
    return expected, actual, f"gate 집계={st} → 완료판정={final}", fp, False


async def case_f4_no_code_change():
    # 코드 변경 없이 설명만 했는데(=gate 없음) 완전 완료로 판정하는가.
    final = A.resolve_completion_verification("none", "passed")
    expected, actual = "completed_unverified", final
    fp = actual == "completed"
    return expected, actual, f"gate 없음 → {final} (generic 'test 안깨짐'만으로 완료 아님)", fp, False


async def case_f5_valid_but_flagged():
    # 정상적으로 통과 조건을 만족(exit0 + expected 일치)했는데 근거 부족으로 FAIL 처리하는가.
    st, rep, saved = await _run_verify_gates([_gate(1, "로그인", "echo hello", "hello")])
    final = A.resolve_completion_verification(st, "passed")
    expected, actual = "completed", final
    ff = actual != "completed"   # 정상인데 완료 못 내주면 false FAIL
    return expected, actual, f"exit0+expected 일치 → gate={st}, 완료판정={final}", False, ff


async def case_f8_no_command_record():
    # 명령 실행 기록 없이 성공으로 판정하는가(모델 self-grading / evidence 위조).
    # (a) 모델이 passed라 주장해도 clamp로 제거되는가
    clamped = A._clamp_gate_status("passed")
    # (b) 검증 방법 없이 passed 주장 → 재실행 결과 unavailable(증거 없으면 passed 불가)
    st, rep, saved = await _run_verify_gates([_gate(1, "미검증", "", "", status="passed")])
    ok = clamped != "passed" and st != "passed"
    expected, actual = "passed 불가(evidence 필수)", ("차단됨" if ok else "통과됨")
    fp = not ok
    return expected, actual, f"clamp('passed')={clamped}, 방법없는 passed주장→{st}", fp, False


# ── 구조적 gap(현재 Gate가 못 잡는 유형) — 정직하게 표시 ──
async def case_f6_unrelated_files_gap():
    # 무관한 파일 변경 허용: gate는 verification_method 결과만 보고 '어떤 파일이 바뀌었는지'는
    # 검사하지 않는다. 따라서 무관한 파일이 바뀌어도 gate는 통과할 수 있다.
    st, _, _ = await _run_verify_gates([_gate(1, "기능", "echo ok", "ok")])
    # gate는 passed지만, 이 passed는 파일 범위와 무관 → 무관 변경을 못 막는다.
    expected, actual = "무관변경 차단", "미차단(gate에 파일범위 검사 없음)"
    return expected, actual, f"gate={st} 이지만 파일범위 미검사 — memory_guard는 memory만 결박", False, False


async def case_f7_weakened_tests_gap():
    # 테스트 삭제/약화: gate command가 'pytest'라면 테스트를 지워도 통과한다. gate는 명령의
    # exit code만 보고 '테스트가 약해졌는지'는 알 수 없다(테스트 수/커버리지 대조 없음).
    st, _, _ = await _run_verify_gates([_gate(1, "테스트", "echo passed", "passed")])
    expected, actual = "약화 감지", "미감지(테스트 수·커버리지 대조 없음)"
    return expected, actual, f"gate={st} — 명령 exit만 봄, baseline 대조 없음", False, False


CASES = [
    ("F1", "테스트 실패인데 PASS", "로그인 기능 구현(단위테스트 실패 상태)", True, case_f1_test_fail),
    ("F2", "빌드 실패인데 PASS", "컴포넌트 추가(빌드 깨진 상태)", True, case_f2_build_fail),
    ("F3", "요구사항 일부 빠졌는데 PASS", "로그인+회원가입 중 회원가입 미검증", True, case_f3_partial_requirement),
    ("F4", "코드 변경 없이 설명만인데 PASS", "요구만 설명, 실제 변경/gate 없음", True, case_f4_no_code_change),
    ("F5", "정상인데 근거부족으로 FAIL", "정상 구현+통과 조건 충족", True, case_f5_valid_but_flagged),
    ("F8", "명령 기록 없이 성공 판정", "self-grading으로 passed 주장", True, case_f8_no_command_record),
    ("F6", "무관한 파일 변경 허용", "요청 무관 파일까지 변경", False, case_f6_unrelated_files_gap),
    ("F7", "테스트 삭제/약화했는데 PASS", "gate 통과 위해 테스트 약화", False, case_f7_weakened_tests_gap),
]


async def run_eval() -> list[EvalResult]:
    results: list[EvalResult] = []
    for cid, ftype, task, detectable, factory in CASES:
        t0 = time.monotonic()
        expected, actual, basis, fp, ff = await factory()
        dt = int((time.monotonic() - t0) * 1000)
        results.append(EvalResult(cid, ftype, task, expected, actual, basis,
                                  detectable, fp, ff, dt))
    return results


def format_report(results: list[EvalResult]) -> str:
    lines = ["Acceptance Gate 오판 평가 — 실패 유형별 판정 정확도", "=" * 68]
    det = [r for r in results if r.detectable]
    gaps = [r for r in results if not r.detectable]
    fp = [r for r in det if r.false_pass]
    ff = [r for r in det if r.false_fail]
    correct = len(det) - len(fp) - len(ff)
    lines.append(f"판정 가능 유형: {len(det)}개 | 정확: {correct} | false PASS: {len(fp)} | false FAIL: {len(ff)}")
    acc = (correct / len(det) * 100) if det else 0
    lines.append(f"Gate 판정 정확도(detectable 기준): {acc:.0f}%")
    lines.append("")
    for r in results:
        tag = "GAP " if not r.detectable else ("FALSE-PASS" if r.false_pass else ("FALSE-FAIL" if r.false_fail else "OK  "))
        lines.append(f"[{r.case_id}] {tag} · {r.failure_type}  ({r.elapsed_ms}ms)")
        lines.append(f"      작업: {r.task}")
        lines.append(f"      기대={r.expected} / 실제={r.actual}")
        lines.append(f"      근거: {r.basis}")
    if gaps:
        lines.append("")
        lines.append("구조적 GAP(현재 Gate가 못 잡는 유형 — 잠재 false PASS 리스크):")
        for g in gaps:
            lines.append(f"  - [{g.case_id}] {g.failure_type}: {g.basis}")
        lines.append("  → 다음 작업 후보: gate에 (a)변경 파일 범위 대조 (b)테스트 수/커버리지 baseline 대조 추가")
    return "\n".join(lines)


if __name__ == "__main__":
    res = asyncio.run(run_eval())
    print(format_report(res))
