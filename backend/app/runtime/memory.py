"""프로젝트 메모리 적립 순수 함수 — agent.py에서 분리.

`_extract_project_memory`의 본문(LLM 호출·파일 쓰기)은 인스턴스 상태(self._adapter_for,
self.router)에 의존하므로 agent.py에 남기고, 여기는 결정적·순수 함수만 둔다.
agent.py는 staticmethod 바인딩으로 기존 이름·동작을 유지한다(외부 인터페이스 불변).
"""
import json
import os
import re


def merge_memory_facts(existing: str, facts: list[str], cap: int = 4000) -> str | None:
    """ROOM_MEMORY에 새 durable 사실을 dedup·상한 적용해 병합한다(순수).
    추가할 게 없거나(중복) 상한을 넘으면 None(무한 성장·중복 방지)."""
    add = [f.strip() for f in facts
           if f.strip() and f.strip().lstrip("-").strip() not in existing]
    if not add:
        return None
    header = "" if "## 학습된 프로젝트 지식" in existing \
        else "\n## 학습된 프로젝트 지식 (FORGE 자동 적립)\n"
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    block = sep + header + "\n".join(add) + "\n"
    if len(existing) + len(block) > cap:
        return None
    return existing + block


def relative_changed(ws: str, files_changed: list) -> list[str]:
    """변경 파일을 워크스페이스 기준 상대 경로로 정규화한다(중복 제거)."""
    out: list[str] = []
    for raw in files_changed or []:
        q = str(raw or "").strip()
        if not q:
            continue
        if os.path.isabs(q):
            try:
                q = os.path.relpath(q, ws)
            except ValueError:
                continue
        q = os.path.normpath(q)
        if q.startswith("..") or q in out:
            continue
        out.append(q)
    return out


def parse_memory_candidates(text: str) -> list[dict]:
    """모델 출력에서 candidate JSON 배열만 뽑는다. 형식이 깨지면 빈 목록(저장 안 함)."""
    t = (text or "").strip()
    if not t:
        return []
    m = re.search(r"\[.*\]", t, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for it in data[:3]:
        if isinstance(it, dict) and it.get("fact"):
            out.append({"fact": str(it.get("fact", "")),
                        "source": str(it.get("source", "")),
                        "evidence": str(it.get("evidence", ""))})
    return out
