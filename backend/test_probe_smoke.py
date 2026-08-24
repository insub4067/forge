"""프로브의 무LLM 이음새 검사를 pytest에서도 돌린다(서버 있을 때만).

경로 이음새 회귀는 단위 테스트가 못 잡는다 — 요청→핸들러→store→응답 전체가 필요하다.
서버가 안 떠 있으면 skip한다(CI에서 서버를 띄우면 자동으로 돈다). 전 과정 LLM 없음.

전체 end-to-end(실제 세션)는 `python probe.py --full`로 별도 실행(비용 발생).
"""
import pytest

import probe


def _server_up():
    try:
        probe.check_health()
        return True
    except probe.ProbeFail:
        return False


pytestmark = pytest.mark.skipif(not _server_up(), reason="FORGE 서버 미실행")


def test_probe_server_responsive_under_listdir():
    probe.check_server_stays_responsive_under_listdir()


def test_probe_model_tier_per_session():
    probe.check_model_tier_per_session()


def test_probe_image_inline():
    probe.check_image_inline()
