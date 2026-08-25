"""Task IR v1 — 파싱·불변식·fallback을 결정적으로 검증(LLM/네트워크 없음, 모의 adapter).

실행: python -m pytest test_task_ir.py -q
"""
import asyncio
import json

from app.runtime.task_ir import (
    TaskIR, Requirement, parse_task_ir, build_interpreter_messages, interpret,
)


def test_parse_valid_assigns_stable_ids():
    data = {
        "intent": "code_change",
        "normalized_goal": "모바일 원격 입력 복구",
        "requirements": [
            {"text": "원격 터치 입력이 다시 동작한다", "source": "user"},
            {"text": "프론트/백엔드 둘 다 점검", "source": "user"},
        ],
        "constraints": ["기존 터치 입력은 깨지면 안 됨"],
        "complexity": "complex", "risk_class": "medium",
    }
    ir = parse_task_ir(data, "원격제어 끊겨. 근본 수정. 기존 터치 유지.")
    assert isinstance(ir, TaskIR) and ir.version == 1
    assert [r.id for r in ir.requirements] == ["R1", "R2"]
    assert ir.constraints == ["기존 터치 입력은 깨지면 안 됨"]
    assert ir.complexity == "complex" and ir.risk_class == "medium"


def test_original_request_is_authority():
    # 모델이 original을 바꿔도 호출측 원문이 최종 authority.
    data = {"intent": "code_change", "original_request": "모델이 지어낸 원문"}
    ir = parse_task_ir(data, "진짜 사용자 원문")
    assert ir.original_request == "진짜 사용자 원문"


def test_parse_json_string_embedded():
    raw = "여기 결과입니다:\n```json\n" + json.dumps({"intent": "question", "requirements": []}) + "\n```"
    ir = parse_task_ir(raw, "이거 왜 안 돼?")
    assert ir is not None and ir.intent == "question"


def test_fallback_on_malformed():
    assert parse_task_ir("설명만 있고 JSON 없음", "요청") is None      # JSON 없음
    assert parse_task_ir(12345, "요청") is None                        # dict 아님
    assert parse_task_ir({"intent": "x"}, "") is None                  # 원문 없음(authority)


def test_invalid_enums_normalized_safely():
    ir = parse_task_ir({"intent": "몰라", "complexity": "무엇", "risk_class": "?"}, "요청")
    assert ir.intent == "code_change"        # 애매하면 안전하게 작업
    assert ir.complexity == "simple" and ir.risk_class == "low"


def test_clarification_carried():
    ir = parse_task_ir({"clarification_required": True,
                        "clarification_question": "어느 화면인가요?"}, "고쳐줘")
    assert ir.clarification_required and ir.clarification_question == "어느 화면인가요?"


def test_build_messages_pure():
    msgs = build_interpreter_messages("테스트 요청")
    assert msgs[0]["role"] == "system" and "발명하지 않는다" in msgs[0]["content"]
    assert msgs[1]["role"] == "user" and msgs[1]["content"] == "테스트 요청"


# ── interpret(): 주입된 모의 adapter로 1회 호출 ──
class _MockAdapter:
    def __init__(self, text=None, raise_exc=False):
        self._text = text
        self._raise = raise_exc

    async def stream_chat(self, messages):
        if self._raise:
            raise RuntimeError("adapter 실패")
        for ch in (self._text or ""):
            yield {"content": ch}


def test_interpret_valid():
    payload = json.dumps({"intent": "code_change",
                          "requirements": [{"text": "A", "source": "user"}]})
    ir = asyncio.run(interpret(_MockAdapter(text=payload), "A를 해줘"))
    assert ir is not None and ir.requirements[0].id == "R1"


def test_interpret_garbage_falls_back_to_none():
    ir = asyncio.run(interpret(_MockAdapter(text="그냥 텍스트, JSON 아님"), "요청"))
    assert ir is None


def test_interpret_adapter_error_does_not_crash():
    # interpreter 실패가 run을 실패시키지 않는다 — 예외를 삼키고 None.
    ir = asyncio.run(interpret(_MockAdapter(raise_exc=True), "요청"))
    assert ir is None
