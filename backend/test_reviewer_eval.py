"""reviewer_eval(R 시리즈) 픽스처·채점 로직 회귀 테스트 (P1-F, 무LLM).

실제 Reviewer 검출력은 `python reviewer_eval.py --run`(LLM 비용)으로 측정한다. 여기서는 LLM 없이
픽스처 유효성·PASS/FAIL 파서·검출률/오탐률 채점을 결정적으로 고정한다.

실행: cd backend && python -m pytest test_reviewer_eval.py -q
"""
import reviewer_eval as R


def test_self_test_runs():
    """픽스처·워크스페이스·파서 전반 self-test."""
    R._self_test()


def test_verdict_parser():
    assert R._verdict_from_text("장문 설명\n마지막에\nFAIL: off-by-one 발견") == "FAIL"
    assert R._verdict_from_text("문제 없음\nPASS") == "PASS"
    assert R._verdict_from_text("애매하게 끝남") == "unknown"


def test_score_detection_and_false_positive():
    defect = R.CASES[0]      # should_flag=True
    clean = R.CASES[6]       # should_flag=False
    perfect = R.score([(defect, "FAIL"), (clean, "PASS")])
    assert perfect["detection_rate"] == 1.0
    assert perfect["false_positive_rate"] == 0.0
    worst = R.score([(defect, "PASS"), (clean, "FAIL")])
    assert worst["detection_rate"] == 0.0
    assert worst["false_positive_rate"] == 1.0


def test_case_set_has_defects_and_cleans():
    defects = [c for c in R.CASES if c.should_flag]
    cleans = [c for c in R.CASES if not c.should_flag]
    assert len(defects) >= 4 and len(cleans) >= 2
    assert len({c.cid for c in R.CASES}) == len(R.CASES)   # 고유 id


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("PASS — reviewer_eval fixtures/scoring (P1-F)")
