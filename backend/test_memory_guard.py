"""Project Memory 오염 방지 검증 (LLM 없음, 결정적).

실제 오염 사례를 회귀 픽스처로 고정한다 — 이 테스트가 통과한다는 것은
그때 발견한 false-memory 버그가 다시 발생하지 않는다는 증거다.

실행: python test_memory_guard.py  (pytest로도 수집된다)
"""
from app.runtime.memory_guard import (
    claim_tokens, format_fact, source_supports, validate_candidate,
)

# 실제 원격 입력 경로가 담긴 source(요약본) — WebSocket/WebRTC는 등장하지 않는다.
REMOTE_SOURCE = """
function toggleRemote(ev) {
  remoteCtrl.value = !!ev.target.checked
  if (remoteCtrl.value) macControls.value = false
}
async function macSend(payload) {
  const r = await fetch('/api/mac/input', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
"""

WS = "/ws"
CHANGED = ["frontend/src/components/RoomsPanel.vue"]
EVIDENCE = ["원격제어 토글 활성화", "python3 -c \"...\""]


def _read(text=REMOTE_SOURCE):
    def read_source(rel):
        return text if rel in CHANGED else None
    return read_source


def _v(cand, existing="", changed=None, evidence=None, text=REMOTE_SOURCE):
    return validate_candidate(
        cand, workspace=WS, changed_files=changed or CHANGED,
        evidence_keys=evidence if evidence is not None else EVIDENCE,
        existing_memory=existing, read_source=_read(text))


def test_case_a_source_and_evidence_backed_fact_is_saved():
    """A. source에 실제 있는 사실 + process evidence → 저장 가능."""
    ok, why = _v({
        "fact": "원격 마우스 입력은 `POST /api/mac/input`으로 전달된다.",
        "source": "frontend/src/components/RoomsPanel.vue",
        "evidence": "원격제어 토글 활성화",
    })
    assert ok, why


def test_case_b_webrtc_false_memory_is_rejected():
    """B. 실제 오염 사례 — source에 없는 기술(WebSocket/WebRTC)을 주장하면 거부.

    실제로 ROOM_MEMORY.md에 영속됐던 문장이다. 구현은 HTTP POST인데 모델이
    "WebSocket/WebRTC 채널로 별도 연결"이라고 지어냈다.
    """
    ok, why = _v({
        "fact": "`toggleRemote`는 UI 상태만 변경하며, 실제 제어는 WebSocket/WebRTC 채널을 통해 별도로 연결되어야 함",
        "source": "frontend/src/components/RoomsPanel.vue",
        "evidence": "원격제어 토글 활성화",
    })
    assert not ok and why == "unsupported_claim", (ok, why)


def test_case_c_nonexistent_source_is_rejected():
    """C. source 파일이 존재하지 않으면 거부."""
    ok, why = _v({"fact": "무언가 사실", "source": "frontend/src/nope.vue",
                  "evidence": "원격제어 토글 활성화"},
                 changed=["frontend/src/nope.vue"])
    assert not ok and why == "invalid_source", (ok, why)


def test_case_d_no_evidence_is_rejected():
    """D. 이번 run의 evidence와 연결되지 않으면 거부."""
    ok, why = _v({"fact": "원격 입력은 `POST /api/mac/input`을 쓴다.",
                  "source": "frontend/src/components/RoomsPanel.vue", "evidence": ""})
    assert not ok and why == "no_evidence", (ok, why)
    ok2, why2 = _v({"fact": "원격 입력은 `POST /api/mac/input`을 쓴다.",
                    "source": "frontend/src/components/RoomsPanel.vue",
                    "evidence": "존재하지 않는 게이트"})
    assert not ok2 and why2 == "no_evidence", (ok2, why2)


def test_case_e_duplicate_is_not_added():
    """E. 이미 있는 fact는 중복 추가하지 않는다."""
    fact = "원격 마우스 입력은 `POST /api/mac/input`으로 전달된다."
    ok, why = _v({"fact": fact, "source": "frontend/src/components/RoomsPanel.vue",
                  "evidence": "원격제어 토글 활성화"},
                 existing=f"## 학습된 프로젝트 지식\n- {fact}\n")
    assert not ok and why == "duplicate", (ok, why)


def test_case_h_generic_advice_without_source_is_rejected():
    """H. 검증되지 않은 일반론은 저장하지 않는다."""
    for cand in (
        {"fact": "테스트는 항상 작성하는 것이 좋다.", "source": "", "evidence": "원격제어 토글 활성화"},
        {"fact": "", "source": "frontend/src/components/RoomsPanel.vue", "evidence": "원격제어 토글 활성화"},
    ):
        ok, why = _v(cand)
        assert not ok, cand
        assert why in ("no_source", "empty_fact"), why


def test_unrelated_source_is_rejected():
    """이번 작업에서 바뀌지 않은 파일을 근거로 삼을 수 없다(아무 파일 인용 방지)."""
    ok, why = _v({"fact": "무언가", "source": "backend/app/main.py",
                  "evidence": "원격제어 토글 활성화"})
    assert not ok and why == "unrelated_source", (ok, why)


def test_path_escape_is_rejected():
    """워크스페이스 밖 경로는 거부한다."""
    for bad in ("../../etc/passwd", "/etc/passwd"):
        ok, why = _v({"fact": "x", "source": bad, "evidence": "원격제어 토글 활성화"},
                     changed=[bad])
        assert not ok and why == "invalid_source", (bad, ok, why)


def test_claim_tokens_and_source_support():
    """주장 토큰 추출과 대조가 의도대로 동작한다."""
    toks = [t.lower() for t in claim_tokens("입력은 `POST /api/mac/input`, WebSocket 아님")]
    assert "/api/mac/input" in toks and "websocket" in toks
    ok, missing = source_supports("WebRTC로 연결된다", REMOTE_SOURCE)
    assert not ok and missing.lower() == "webrtc"
    ok2, _ = source_supports("`macSend`가 전송한다", REMOTE_SOURCE)
    assert ok2
    # 검사할 토큰이 없는 순수 서술은 여기서 막지 않는다(다른 검증이 담당).
    assert source_supports("이 프로젝트는 좋다", REMOTE_SOURCE)[0]


def test_format_fact_carries_provenance():
    """저장 형식에 provenance(source·evidence)가 함께 남는다."""
    out = format_fact({"fact": "원격 입력은 `POST /api/mac/input`을 쓴다.",
                       "source": "frontend/src/components/RoomsPanel.vue",
                       "evidence": "gate:원격제어 토글 활성화"})
    assert out.startswith("- 원격 입력은")
    assert "source: `frontend/src/components/RoomsPanel.vue`" in out
    assert "verified: gate:원격제어 토글 활성화" in out


# ─── 런타임 결합부: candidate 파싱 / 변경파일 정규화 ───

def test_parse_candidates_rejects_broken_output():
    """모델이 JSON을 안 내면 저장하지 않는다(형식 깨짐 = 아무것도 안 함)."""
    from app.runtime.agent import AgentRuntime as A
    p = A._parse_memory_candidates
    assert p("") == []
    assert p("NONE") == []
    assert p("- 그냥 불릿 한 줄") == []          # 옛 자유서술 형식은 더 이상 통과 못 함
    assert p("[{broken json") == []
    assert p('{"fact":"x"}') == []                # 배열이 아니면 거부


def test_parse_candidates_extracts_structured_facts():
    from app.runtime.agent import AgentRuntime as A
    out = A._parse_memory_candidates(
        '설명 텍스트 [{"fact":"F1","source":"a.py","evidence":"E1"},'
        '{"fact":"F2","source":"b.py","evidence":"E2"}] 뒤에 잡담')
    assert out == [{"fact": "F1", "source": "a.py", "evidence": "E1"},
                   {"fact": "F2", "source": "b.py", "evidence": "E2"}]
    # 최대 3개까지만
    many = "[" + ",".join('{"fact":"f%d","source":"s","evidence":"e"}' % i for i in range(6)) + "]"
    assert len(A._parse_memory_candidates(many)) == 3


def test_relative_changed_normalizes_and_drops_outside():
    """절대경로는 워크스페이스 상대로, 밖의 경로는 버린다."""
    from app.runtime.agent import AgentRuntime as A
    out = A._relative_changed("/ws", ["/ws/a.py", "b/c.py", "/etc/passwd", "/ws/a.py", ""])
    assert "a.py" in out and "b/c.py" in out
    assert not any(o.startswith("..") for o in out)
    assert len(out) == len(set(out))            # 중복 제거


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("메모리 오염 방지 테스트 통과 ✓")
