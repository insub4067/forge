"""테스트는 운영 로그를 절대 건드리지 않는다.

실제로 일어난 일: `rt.run(...)`을 도는 테스트가 `logs/events-*.jsonl`에
`session_id="s1"` 가짜 run을 쌓았고, gate 커버리지 집계가 그 가짜 run을 실제 사용
데이터로 읽었다. 계측 기반으로 결정을 내리는 프로젝트에서 오염된 telemetry는
잘못된 결론을 만든다.

개별 테스트가 `eventlog.record`를 목킹하는 것에 의존하지 않는다 — 빼먹으면 조용히
오염되기 때문이다. 로그 디렉터리 자체를 임시 경로로 돌려 구조적으로 막는다.
app 모듈이 import되기 **전에** env를 세팅해야 LOG_DIR 상수에 반영된다.
"""
import os
import tempfile

_TMP_LOGS = os.environ.setdefault(
    "FORGE_LOG_DIR", tempfile.mkdtemp(prefix="forge-test-logs-"))


def pytest_report_header(config):
    return f"eventlog → {_TMP_LOGS} (운영 logs/ 격리)"
