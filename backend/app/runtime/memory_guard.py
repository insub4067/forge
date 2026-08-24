"""Project Memory 오염 방지 — candidate fact를 evidence에 결박하는 결정적 검증(순수 함수).

**LLM 출력은 evidence가 아니다.** utility 모델은 주어진 검증 사실을 압축만 할 수 있고,
새 사실을 만들어낼 수 없다. 여기서 그 경계를 기계적으로 강제한다.

실제 오염 사례(2026-08-24):
    "RoomsPanel.vue의 toggleRemote는 UI 상태만 변경하며,
     실제 제어는 WebSocket/WebRTC 채널을 통해 별도로 연결되어야 함"
실제 구현은 pointer event → macSend() → POST /api/mac/input 이다. WebSocket은 터미널
전용이고 원격 입력과 무관하다. 이 거짓 사실이 ROOM_MEMORY에 영속돼 이후 모든 세션의
system context에 실렸다. 한 번 들어간 잘못된 기억은 이후 모든 작업을 오염시킨다.

원칙: 모르는 것 > 틀리게 기억하는 것. 애매하면 저장하지 않는다.
"""
import os
import re

# fact에서 뽑아내는 '검증 대상 주장 토큰'.
# 이 토큰들이 인용한 source에 실제로 없으면 모델이 지어낸 것으로 본다.
_TECH_TOKENS = (
    "websocket", "webrtc", "grpc", "graphql", "sse", "eventsource",
    "redis", "kafka", "rabbitmq", "mqtt", "socket.io",
    "webgl", "canvas", "worker", "indexeddb", "localstorage", "sessionstorage",
)

REJECT_REASONS = (
    "empty_fact", "no_source", "invalid_source", "unrelated_source",
    "no_evidence", "duplicate", "unsupported_claim",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def claim_tokens(fact: str) -> list[str]:
    """fact가 주장하는, source에서 확인 가능해야 하는 토큰들.

    - 백틱 코드(`POST /api/mac/input`, `toggleRemote`)
    - /api/... 경로
    - 알려진 기술 이름(WebSocket, WebRTC 등)

    자연어 서술은 검사하지 않는다 — 구조적으로 확인 가능한 주장만 본다.
    """
    out: list[str] = []
    for m in re.findall(r"`([^`]+)`", fact or ""):
        t = m.strip()
        # 백틱 안에서도 식별자·경로만 검사한다(문장은 제외).
        for piece in re.findall(r"/[A-Za-z0-9_\-/]+|[A-Za-z_][A-Za-z0-9_]{2,}", t):
            if piece not in out:
                out.append(piece)
    for m in re.findall(r"/api/[A-Za-z0-9_\-/]+", fact or ""):
        if m not in out:
            out.append(m)
    low = (fact or "").lower()
    for t in _TECH_TOKENS:
        if t in low and t not in [o.lower() for o in out]:
            out.append(t)
    return out


def source_supports(fact: str, source_text: str) -> tuple[bool, str]:
    """fact의 주장 토큰이 인용한 source 안에 실제로 있는가.

    하나라도 없으면 거짓 주장으로 본다 — WebRTC 사례가 정확히 여기 걸린다
    (fact는 WebSocket/WebRTC를 말하는데 인용 파일엔 그 문자열이 없다).
    검사할 토큰이 하나도 없으면(순수 자연어 서술) 통과시키되, 호출자가 다른
    검증(evidence·관련성)으로 거른다.
    """
    tokens = claim_tokens(fact)
    if not tokens:
        return True, ""
    low = (source_text or "").lower()
    for t in tokens:
        if t.lower() not in low:
            return False, t
    return True, ""


def validate_candidate(cand: dict, *, workspace: str, changed_files: list,
                       evidence_keys: list, existing_memory: str,
                       read_source) -> tuple[bool, str]:
    """candidate 하나를 결정적으로 검증한다. (통과여부, 거절사유).

    read_source(rel_path) -> str|None : source 본문을 읽는 주입 함수(테스트 가능).
    """
    fact = _norm(cand.get("fact", ""))
    source = _norm(cand.get("source", ""))
    evidence = _norm(cand.get("evidence", ""))

    if not fact:
        return False, "empty_fact"
    if not source:
        return False, "no_source"

    # source는 워크스페이스 안의 상대 경로여야 한다(경로 탈출·절대경로 금지).
    if os.path.isabs(source) or source.startswith(".."):
        return False, "invalid_source"
    norm = os.path.normpath(source)
    if norm.startswith("..") or os.path.isabs(norm):
        return False, "invalid_source"

    # 이번 작업과 무관한 파일을 근거로 삼을 수 없다(아무 파일이나 인용해 통과하는 것 방지).
    changed = {os.path.normpath(str(c)) for c in (changed_files or [])}
    if norm not in changed:
        return False, "unrelated_source"

    text = read_source(norm)
    if text is None:
        return False, "invalid_source"

    # evidence는 이번 run의 실제 gate/검증 명령이어야 한다.
    if not evidence or not any(evidence in k or k in evidence for k in (evidence_keys or [])):
        return False, "no_evidence"

    ok, missing = source_supports(fact, text)
    if not ok:
        return False, "unsupported_claim"

    if fact and fact in (existing_memory or ""):
        return False, "duplicate"

    return True, ""


def format_fact(cand: dict) -> str:
    """검증 통과한 fact를 provenance와 함께 Markdown 한 항목으로."""
    fact = _norm(cand.get("fact", ""))
    source = _norm(cand.get("source", ""))
    evidence = _norm(cand.get("evidence", ""))
    line = f"- {fact}"
    prov = f"  - source: `{source}`"
    if evidence:
        prov += f" · verified: {evidence}"
    return line + "\n" + prov
