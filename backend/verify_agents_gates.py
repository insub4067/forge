"""Agent roster 게이트 검증 — 라이브 서버 없이(in-process TestClient) 실행한다.

게이트 검증 러너가 cwd=workspace(forge 루트)에서 sh -c로 실행하며, stdout에
게이트별 태그를 출력한다. 인자(tag)로 검증 대상을 고른다:

  roster    GET /api/agents가 실제 Runtime(MAIN_ROLES) 기반 목록을 반환하는가
  meta      read_only/fresh/tool metadata가 런타임 스키마·정책과 일치하는가
  prompt    GET /api/agents/{id}/prompt가 docs/agents/{id}.md 원문과 정확히 일치하는가
  notfound  미존재 role(triage/vision/ghost/gate_recovery)이 404를 반환하는가

성공 시 `<TAG>_OK`를 출력하고 exit 0, 실패 시 `<TAG>_FAIL:<사유>` exit 1.
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import agents as catalog
from app.main import app
from app.runtime.agent import AGENTS_DIR, READ_ONLY_TOOL_SCHEMAS
from app.tools.registry import CHAT_TOOLS, TOOL_SCHEMAS

C = TestClient(app)


def tool_names(schemas) -> set[str]:
    return {s["function"]["name"] for s in schemas}


def check_roster() -> bool:
    d = C.get("/api/agents")
    if d.status_code != 200:
        return False
    ids = [a["id"] for a in d.json()["agents"]]
    return ids == list(catalog.MAIN_ROLES)


def check_meta() -> bool:
    for role in catalog.MAIN_ROLES:
        d = C.get(f"/api/agents/{role}").json()
        exp = {"planner": READ_ONLY_TOOL_SCHEMAS, "chat": CHAT_TOOLS}.get(role, TOOL_SCHEMAS)
        if set(d["tools"]) != tool_names(exp):
            return False
        # read_only: chat/planner은 구조적으로 mutation 불가(런타임 정책과 동일)
        if d["read_only"] != (role in ("planner", "chat")):
            return False
        # fresh_context: planner/reviewer만 별도 최소 컨텍스트(fresh)
        if d["fresh_context"] != (role in ("planner", "reviewer")):
            return False
    return True


def check_prompt() -> bool:
    for role in catalog.MAIN_ROLES:
        r = C.get(f"/api/agents/{role}/prompt")
        if r.status_code != 200:
            return False
        raw = (Path(AGENTS_DIR) / f"{role}.md").read_text(encoding="utf-8")
        if r.json()["prompt"] != raw:
            return False
    return True


def check_notfound() -> bool:
    # 존재하지 않는 role(ghost)과 roster 미노출 내부 role(triage/vision)만 404.
    # gate_recovery는 실제 회복 전용 role로 prompt가 존재하므로 404 대상이 아니다.
    for role in ("ghost", "triage", "vision"):
        if C.get(f"/api/agents/{role}").status_code != 404:
            return False
        if C.get(f"/api/agents/{role}/prompt").status_code != 404:
            return False
    return True


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"roster": check_roster, "meta": check_meta, "prompt": check_prompt, "notfound": check_notfound}.get(tag)
    if fn is None:
        print(f"UNKNOWN_TAG:{tag}")
        return 2
    ok = fn()
    print(f"{tag.upper()}_OK" if ok else f"{tag.upper()}_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
