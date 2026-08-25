"""Gate 오판 평가 회귀 — 판정 가능 유형에서 false PASS/FAIL이 0인지, 구조적 gap이 계속
인식되는지 결정적으로 확인한다(LLM/네트워크 없음).

실행: python -m pytest test_gate_eval.py -q
"""
import asyncio

from gate_eval import run_eval


def test_gate_eval_no_false_pass_or_fail():
    results = asyncio.run(run_eval())
    det = [r for r in results if r.detectable]
    fp = [r for r in det if r.false_pass]
    ff = [r for r in det if r.false_fail]

    # 가장 위험한 실패: 실패인데 통과(false PASS)는 0이어야 한다.
    assert not fp, f"false PASS 발생: {[(r.case_id, r.expected, r.actual) for r in fp]}"
    # 정상인데 근거부족으로 막는 false FAIL도 0이어야 한다.
    assert not ff, f"false FAIL 발생: {[(r.case_id, r.expected, r.actual) for r in ff]}"

    # 판정 가능 유형이 유지되는지(케이스가 조용히 사라지지 않도록).
    # F7(테스트 약화)은 change_guard 감지 추가로 gap → detectable로 승격됨.
    assert len(det) == 7, [r.case_id for r in det]

    # 남은 구조적 gap: F6(무관 파일 변경)만. 이걸 잡게 되면(gate 강화) 여기서 실패시켜
    # 케이스 재분류를 강제한다 — 잠재 false PASS 리스크를 잊지 않기 위함.
    gaps = {r.case_id for r in results if not r.detectable}
    assert gaps == {"F6"}, gaps
