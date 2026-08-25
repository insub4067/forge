"""Task IR 라우팅 통합(관찰 전용, 기본 off) 검증 — 플래그 게이트와 이벤트 발행.

실행: python -m pytest test_task_ir_integration.py -q
"""
import asyncio
import json

from app.runtime import agent as A


class _MockAdapter:
    def __init__(self, text):
        self._text = text

    async def stream_chat(self, messages):
        yield {"content": self._text}


def _run_maybe_interpret(enabled: bool, full_request: str, adapter_text: str):
    rt = A.AgentRuntime()
    events = []

    async def send(event_type, data):
        events.append((event_type, data))

    rt._adapter_for = lambda model: _MockAdapter(adapter_text)  # flash 호출 대체

    old = A.settings.task_ir_enabled
    A.settings.task_ir_enabled = enabled
    try:
        ir = asyncio.run(rt._maybe_interpret(full_request, send))
    finally:
        A.settings.task_ir_enabled = old
    return ir, events


def test_flag_off_is_noop():
    # 기본 off — 어댑터 호출도, 이벤트도 없다(동작·비용 불변).
    ir, events = _run_maybe_interpret(False, "무언가 고쳐줘", json.dumps({"intent": "code_change"}))
    assert ir is None and events == []


def test_flag_on_emits_task_ir_event():
    payload = json.dumps({"intent": "code_change",
                          "requirements": [{"text": "A", "source": "user"}]})
    ir, events = _run_maybe_interpret(True, "A를 해줘", payload)
    assert ir is not None and ir.requirements[0].id == "R1"
    assert any(e[0] == "task_ir" for e in events), events
    payloads = [d for (t, d) in events if t == "task_ir"]
    assert payloads[0]["task_ir"]["original_request"] == "A를 해줘"  # 원문 authority 보존


def test_flag_on_garbage_no_event_no_crash():
    # 파싱 실패 시 이벤트 없이 조용히 fallback(라우팅 그대로).
    ir, events = _run_maybe_interpret(True, "요청", "JSON 아님, 그냥 텍스트")
    assert ir is None and not any(e[0] == "task_ir" for e in events)


def test_empty_request_noop_even_when_on():
    ir, events = _run_maybe_interpret(True, "", "{}")
    assert ir is None and events == []


def test_requirements_stored_under_session_for_completion():
    # Task IR가 켜지면 요구사항을 세션 키로 보관해 완료 시 gate와 대조할 수 있어야 한다.
    payload = json.dumps({"intent": "code_change",
                          "requirements": [{"text": "A", "source": "user"},
                                           {"text": "B", "source": "user"}]})
    rt = A.AgentRuntime()
    rt._adapter_for = lambda model: _MockAdapter(payload)

    async def send(t, d):
        pass

    old = A.settings.task_ir_enabled
    A.settings.task_ir_enabled = True
    try:
        asyncio.run(rt._maybe_interpret("A와 B를 해줘", send, "sess-1"))
    finally:
        A.settings.task_ir_enabled = old

    reqs = rt._task_ir_reqs.get("sess-1")
    assert reqs and [r["id"] for r in reqs] == ["R1", "R2"]

    # 완료 글루 재현: pop 후 gate와 대조 → traceability. R1만 passed면 R2 미검증.
    from app.runtime import traceability
    gates = [{"requirement_id": "R1", "status": "passed"}]
    m = traceability.compute_traceability(rt._task_ir_reqs.pop("sess-1"), gates)
    assert m["requirements_total"] == 2 and m["requirements_verified"] == 1
    assert m["false_completion_candidate"] is True and m["unverified_ids"] == ["R2"]
    assert "sess-1" not in rt._task_ir_reqs  # pop으로 누수 방지


def test_no_session_id_still_works_and_stores_nothing():
    # session_id 없이 호출해도(하위호환) 저장 없이 이벤트만 발행.
    ir, events = _run_maybe_interpret(
        True, "A를 해줘",
        json.dumps({"intent": "code_change", "requirements": [{"text": "A"}]}))
    assert ir is not None and any(e[0] == "task_ir" for e in events)


def test_end_to_end_traceability_event_on_completion():
    """실제 run() 완료 경로에서 traceability 이벤트가 발화하는지(글루 회귀).

    flag ON + 요구사항 2개(R1,R2), gate는 R1만 passed로 연결 → R2 미검증 →
    false_completion 후보. run()이 done과 함께 traceability를 emit해야 한다.
    """
    from test_reliability_invariants import make_rt  # run()을 구동하는 목킹 하네스 재사용

    rt, _ = make_rt(["passed"])  # verify passed → 정상 완료 경로
    rt._adapter_for = lambda model: _MockAdapter(json.dumps({
        "intent": "code_change",
        "requirements": [{"text": "A", "source": "user"},
                         {"text": "B", "source": "user"}]}))

    async def _linked_gates(*a, **k):
        # R1만 gate로 연결·passed, R2는 gate 없음. id/title은 _verify_gates가 읽는다.
        return [{"id": 1, "title": "R1작업", "requirement_id": "R1", "status": "passed",
                 "verification_method": "", "expected_result": "", "failure_reason": ""}]
    A.store.list_gates = _linked_gates

    events = []

    async def emit(e):
        events.append(e)

    old = A.settings.task_ir_enabled
    A.settings.task_ir_enabled = True
    try:
        asyncio.run(rt.run([{"role": "user", "content": "A와 B를 해줘"}],
                           emit, "s1", "/tmp"))
    finally:
        A.settings.task_ir_enabled = old

    types = [e["type"] for e in events]
    tr = [e for e in events if e["type"] == "traceability"]
    assert tr, f"traceability 이벤트가 없다: {types}"
    d = tr[-1]["data"]
    assert d["requirements_total"] == 2 and d["requirements_verified"] == 1
    assert d["false_completion_candidate"] is True and d["unverified_ids"] == ["R2"]
    # flag OFF면 이 경로가 전혀 없어야 한다(관찰 전용·기본 불변) — 대조.
    events.clear()
    asyncio.run(rt.run([{"role": "user", "content": "A와 B를 해줘"}], emit, "s1", "/tmp"))
    assert not any(e["type"] == "traceability" for e in events)
