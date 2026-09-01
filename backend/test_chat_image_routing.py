"""이미지 첨부 턴이 chat으로 라우팅돼도 실제로 '읽히는지' 검증 (LLM 없음).

실측 버그(세션 e11ba4b4…): 사용자가 이미지를 올리고 "관상 봐줘"라고 하자 triage가 이를
대화(CHAT)로 분류 → chat 경로가 `_run_role("chat", …)`를 호출하며 `has_image`를 넘기지
않아(기본 False) ①비전 모델 미선택 ②이미지 미전송 → 모델이 "이미지를 볼 수 없습니다"라고
세 번 답했다. 이음새(run→chat role→select_model / 전송 투영)에서 조용히 실패하는 종류라
테스트로 고정한다.

두 축:
  1. 라우터: chat + 이미지 → vision 모델(텍스트 flash는 이미지 400).
  2. 이음새: run()이 chat 역할 호출에 has_image=True를 전달한다.

실행: cd backend && python -m pytest test_chat_image_routing.py -q
"""
import asyncio

from app.orchestrator.model_router import ModelRouter
from app.runtime import agent as A

_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# ── 축 1: 라우터 ──────────────────────────────────────────────
def test_chat_image_routes_to_vision():
    r = ModelRouter()
    # chat + 이미지 → vision (텍스트 flash면 이미지 400)
    assert r.select_model("chat", has_image=True)["model"] == r._policy["vision"]["model"]
    # 이미지 없으면 기존대로 최저가 flash
    assert "flash" in r.select_model("chat", has_image=False)["model"]
    # developer + 이미지도 여전히 vision (회귀 방지)
    assert r.select_model("developer", has_image=True)["model"] == r._policy["vision"]["model"]


# ── 축 2: 이음새 (run → chat role) ────────────────────────────
def _make_runtime():
    rt = A.AgentRuntime()
    calls = []  # (role, has_image)

    async def fake_run_role(role, all_messages, send, session_id, ws, state,
                            recent_calls, step_base, room_memory="", retry_count=0,
                            tools=None, skills="", complexity="normal", escalate=False,
                            has_image=False, plan="", requirements=""):
        calls.append((role, has_image))
        return "done", 0, 0, {"model": "m", "thinking": False, "reasoning_effort": ""}

    rt._run_role = fake_run_role

    async def fake_triage(all_messages):
        return "chat", 0, 0
    rt._triage = fake_triage

    async def _noop(*a, **k):
        return None

    async def _empty(*a, **k):
        return []

    A.store.save_agent_run = _noop
    A.store.update_context_usage = _noop
    A.store.ensure_session = _noop
    A.store.save_history = _noop
    A.store.set_session_final_status = _noop
    A.store.list_tasks = _empty
    A.store.replace_tasks = _noop
    A.store.list_gates = _empty
    A.store.replace_gates = _noop
    A.store.save_gate_result = _noop
    return rt, calls


def test_run_forwards_has_image_to_chat_role():
    rt, calls = _make_runtime()
    msg = {"role": "user", "content": [
        {"type": "text", "text": "저 남자 관상 봐줘"},
        {"type": "image_url", "image_url": {"url": _PNG}},
    ]}

    async def emit(evt):
        return None

    asyncio.run(rt.run([msg], emit, "s_img", None))
    chat_calls = [ci for ci in calls if ci[0] == "chat"]
    assert chat_calls, f"chat 역할이 호출되지 않음: {calls}"
    assert all(hi for _, hi in chat_calls), f"chat 호출에 has_image가 전달되지 않음: {chat_calls}"
