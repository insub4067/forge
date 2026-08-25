"""완료/게이트 판정 정책 — 순수 함수 모음(상태·부작용 없음).

agent.py에서 분리한 첫 책임 단위. '무엇을 검증된 완료로 볼 것인가'와 '모델이 어떤 상태를
설정할 수 있는가'라는 정책만 담는다. 런타임 실행 상태에 의존하지 않으므로 독립적으로
테스트·재사용 가능하고, agent.py는 이 모듈을 import해 기존 이름을 그대로 노출한다
(외부 인터페이스 불변). 순환 의존 없음(이 모듈은 agent를 import하지 않는다).
"""


def needs_gate_recovery(route_kind: str, files_changed: list, gate_count: int) -> bool:
    """gate 복구가 필요한 상황인가 — 새 LLM 분류 호출 없이 기존 runtime state만 본다.

    조건: 작업(code) run + 실제 파일 변경 발생 + gate 0개.
    `files_changed`가 비어 있지 않다는 것 자체가 mutation 작업이었다는 가장 강한 증거다
    (설명·조회·리뷰 요청은 파일을 바꾸지 않으므로 여기 걸리지 않는다). 별도 분류기를
    두면 비용이 늘고 오분류가 새 실패 모드를 만든다.
    """
    return route_kind == "code" and bool(files_changed) and gate_count == 0


def _coverage_kind(gate_count: int, files_changed: list, recovered: bool,
                   is_code: bool) -> str:
    """이 run이 어떤 경로로 마감됐는지 분류한다(telemetry). 상태를 바꾸지 않는다.

    gated           — gate가 있었고 정상 흐름을 탔다
    recovered_gated — gate가 없어 복구 턴이 만들어 냈다
    generic_only    — 복구 후에도 gate 0. 요구사항 미검증(가장 주의해야 할 분류)
    no_change       — 코드 변경 없음(gate가 필요 없다)
    not_applicable  — 작업 run이 아니다(대화·조회)
    """
    if not is_code:
        return "not_applicable"
    if not files_changed:
        return "no_change"
    if gate_count == 0:
        return "generic_only"
    return "recovered_gated" if recovered else "gated"


def _blocking_reason(status: str, gstate: str, vstate: str) -> str:
    """왜 완전히 검증된 완료가 아닌가 — 한 가지 사유만(가장 근본적인 것)."""
    if status == "completed":
        return ""
    if gstate == "none":
        return "요구사항 게이트 없음"
    if gstate == "failed":
        return "요구사항 검증 실패"
    if vstate != "passed":
        return "실행 가능한 test/build 없음"
    return "일부 요구사항 미검증"


def resolve_completion_verification(gstate: str, vstate: str,
                                    requirement_gap: bool = False) -> str:
    """최종 완료 상태를 결정한다(순수 함수 — 이 프로젝트의 핵심 invariant).

    **gate가 없는 코드 변경은 완전히 검증된 완료가 아니다.** generic verification은
    "기존 test/build가 안 깨졌다"만 말하고 사용자 요구사항 충족은 확인하지 않는다.
    gate 0으로 `completed`를 내주면 모델이 요구사항을 놓쳐도 완료로 둔갑한다
    (false_completion — 이 프로젝트가 가장 위험하게 보는 실패).

    gate 없음 ≠ verification_failed (실패한 게 아니다)
    gate 없음 ≠ completed        (완전히 검증된 것도 아니다)
    gate 없음 = completed_unverified

    requirement_gap=True는 Task IR requirement 중 passed gate로 이어지지 않은 것이 있다는
    뜻이다(traceability.false_completion_candidate). gate 자체는 통과했어도 요구사항 하나가
    검증되지 않은 채 완료로 나가는 것이 false_completion이므로 completed를 주지 않는다.
    **차단이 아니라 강등이다** — 완료는 시키되 검증됐다고 말하지 않는다(false-block 회피).
    Task IR이 꺼져 있거나 requirement가 없으면 호출측이 False를 주므로 동작이 바뀌지 않는다.
    """
    if requirement_gap:
        return "completed_unverified"
    if gstate == "none":
        return "completed_unverified"
    if gstate == "passed" and vstate == "passed":
        return "completed"
    return "completed_unverified"


# 칸반 invariant: 모델은 todo/working만 설정한다. testing→done은 프로세스(검증 게이트·
# _finalize_tasks)가 소유하므로, 모델이 넣은 done/testing/레거시 상태를 강등한다.
_TASK_STATUS_CLAMP = {
    "todo": "todo", "working": "working",
    "planning": "todo", "in_progress": "working", "in-progress": "working",
    "review": "working", "debug": "working",
}


def _clamp_task_status(status: str) -> str:
    """모델이 설정할 수 있는 task 상태를 todo/working으로 제한한다(done/testing은 프로세스만)."""
    return _TASK_STATUS_CLAMP.get(str(status), "working")


# gate 상태 invariant: 모델은 pending/working/blocked/abandoned/unavailable(선언)만 쓴다.
# passed/failed는 검증을 실제로 실행한 프로세스만 설정한다(self-grading 방지).
_GATE_STATUS_CLAMP = {
    "pending": "pending", "working": "working",
    "blocked": "blocked", "abandoned": "abandoned",
    "unavailable": "unavailable",  # 모델이 "검증 방법 없음"을 선언 — 프로세스가 재확인 후 확정
}


def _clamp_gate_status(status: str) -> str:
    """모델이 설정할 수 있는 gate 상태로 제한한다(passed/failed는 프로세스 전용)."""
    return _GATE_STATUS_CLAMP.get(str(status), "working")
