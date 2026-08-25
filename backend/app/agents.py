"""Agent Roster / Crew catalog — 실제 Runtime이 source of truth.

Agent Definition(어떤 에이전트가 존재하고, 무슨 모델·도구·프롬프트로 움직이는지)을
runtime의 실제 상수에서 파생한다. frontend에 복제하지 않고 read-only API로만 노출한다.

- 역할·도구: tools/registry.py의 TOOL_SCHEMAS / CHAT_TOOLS,
             runtime/agent.py의 READ_ONLY_TOOL_SCHEMAS(Planner), GATE_RECOVERY_TOOL_SCHEMAS
- 모델·thinking: orchestrator/model_router.py의 ModelRouter policy
- fresh context 여부: runtime/agent.py의 _planner_context / _reviewer_context가
  별도 최소 컨텍스트를 만든다(planner·reviewer = fresh, developer·chat = persistent)
- system prompt: docs/agents/{role}.md 원문(동적 memory/skills/plan은 붙이지 않는다)

이 모듈은 observability 전용이다 — runtime 동작을 바꾸지 않는다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import settings
from .tools.registry import APPROVAL_REQUIRED, CHAT_TOOLS, TOOL_SCHEMAS
from .runtime.agent import (
    AGENTS_DIR,
    GATE_RECOVERY_TOOL_SCHEMAS,
    READ_ONLY_TOOL_SCHEMAS,
)
from .orchestrator.model_router import ModelRouter

# main roster에 노출할 role — 실제 runtime이 호출하는 role만. vision/triage는
# 에이전트가 아니라 라우팅·모델 선택이라 기본 roster에서 제외한다(내부 섹션 참고).
MAIN_ROLES = ("developer", "planner", "reviewer", "chat")

# role → 실제로 `_run_role`에 넘겨지는 tool schema.
# developer: tools 미지정 → TOOL_SCHEMAS 전체.
# planner:   READ_ONLY_TOOL_SCHEMAS(읽기 4종만).
# reviewer:  READ_ONLY_TOOL_SCHEMAS — 프롬프트가 아니라 런타임 스키마로 write/edit/bash/build/
#            skill을 결정적으로 차단한다(프롬프트를 보안 경계로 쓰지 않는다). 프로세스가
#            _verify/_verify_integration로 독립 검증하므로 Reviewer는 코드 리뷰에 집중한다.
# chat:      CHAT_TOOLS(읽기·질문·browser만).
_ROLE_TOOLS: dict[str, list[dict]] = {
    "developer": TOOL_SCHEMAS,
    "planner": READ_ONLY_TOOL_SCHEMAS,
    "reviewer": READ_ONLY_TOOL_SCHEMAS,
    "chat": CHAT_TOOLS,
}

# fresh context 여부 — _planner_context/_reviewer_context가 최근 최소 맥락만 받는다.
_FRESH_CONTEXT = {"planner", "reviewer"}

# role → 정책상 사용 제약(스키마와 별개). 빈 문자열이면 제약 없음.
_POLICY_NOTE = {
    "reviewer": "읽기 전용 스키마(read/list/grep/find_symbol)로 write/edit/bash/build/skill이 "
                "런타임에서 결정적으로 차단됩니다. 독립 검증은 프로세스가 수행합니다.",
}

# 표시 메타데이터(발음·카테고리·성격 문구). 런타임 로직이 아니라 presentation layer다.
_DISPLAY: dict[str, dict] = {
    "developer": {
        "display_name": "제작자",
        "category": "Core",
        "icon": "hammer",
        "flavor": "계획을 실제 코드로 만듭니다.",
        "description": "설계·구현·자체검증을 한 루프에서 수행하는 FORGE의 유일한 실행 에이전트. "
                       "간단 작업은 단독으로, 복잡 작업은 Planner 계획 뒤에 붙고 Reviewer 검증이 뒤따릅니다.",
    },
    "planner": {
        "display_name": "전략가",
        "category": "Planning",
        "icon": "map",
        "flavor": "먼저 길을 찾습니다.",
        "description": "복잡한 코드 작업에서 실행 가능한 계획만 세우는 fresh-context 에이전트. "
                       "구현·수정·명령 실행은 하지 않으며, 사용자 요청과 최근 최소 맥락만 받습니다.",
    },
    "reviewer": {
        "display_name": "검토자",
        "category": "Verification",
        "icon": "magnifier",
        "flavor": "끝났다는 말을 믿지 않습니다.",
        "description": "Developer가 완료한 작업을 독립적인 시각으로 검증하는 fresh-context 에이전트. "
                       "Developer의 작업 기록을 주지 않고 git diff·테스트·빌드로 직접 확인합니다.",
    },
    "chat": {
        "display_name": "안내자",
        "category": "Conversation",
        "icon": "chat",
        "flavor": "코드를 건드리지 않고 답합니다.",
        "description": "코드 수정이 필요 없는 대화·질문·설명에 단일 패스로 답하는 에이전트. "
                       "읽기·질문 도구만 받아 mutation을 구조적으로 할 수 없습니다.",
    },
}

# 내부 System/Utility — roster 카드가 아니라 하단 작은 섹션으로만 노출한다.
_INTERNAL: dict[str, dict] = {
    "gate_recovery": {
        "name": "Gate Recovery",
        "category": "Internal · Recovery",
        "flavor": "구현은 끝났는데 검증 게이트가 없을 때 한 번만 등록합니다.",
        "prompt_available": True,
    },
    "triage": {
        "name": "Triage",
        "category": "Internal · Router",
        "flavor": "요청이 대화인지 코드 작업인지 최저가 모델로 가릅니다.",
        "prompt_available": False,
    },
    "vision": {
        "name": "Vision",
        "category": "Internal · Model Route",
        "flavor": "이미지가 있는 턴에서 Developer를 대신해 이미지를 받는 모델 경로입니다.",
        "prompt_available": False,
    },
}

# 도구 카테고리 — badge 표현용(도구 목록 자체는 위 _ROLE_TOOLS가 source of truth).
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "read_file": "파일 내용 읽기",
    "list_dir": "디렉터리 목록",
    "grep": "패턴 검색",
    "write_file": "파일 생성·덮어쓰기",
    "edit_file": "파일 수정",
    "bash": "셸 명령 실행",
    "build_frontend": "프론트엔드 빌드",
    "ask_user": "사용자 질문",
    "update_tasks": "칸반 태스크 갱신",
    "update_gates": "요구사항 게이트 등록",
    "save_skill": "스킬 저장",
    "find_symbol": "심볼 탐색",
    "read_tool_result": "도구 결과 재조회",
    "browser_check": "브라우저 스모크",
}


def _role_tool_names(role: str) -> list[str]:
    return [t["function"]["name"] for t in _ROLE_TOOLS[role]]


def _read_only(role: str) -> bool:
    """role이 받는 tool schema에 mutation 도구(승인 필요)가 하나도 없으면 read-only."""
    return not any(name in APPROVAL_REQUIRED for name in _role_tool_names(role))


def _prompt_text(role: str) -> str:
    """docs/agents/{role}.md 원문. 없으면 빈 문자열."""
    path = AGENTS_DIR / f"{role}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _prompt_hash(role: str) -> str:
    return hashlib.sha256(_prompt_text(role).encode("utf-8")).hexdigest()[:12]


def _policy(role: str) -> dict:
    """ModelRouter policy — 모델·thinking·reasoning_effort의 단일 source of truth."""
    roles = ModelRouter().get_policy()["roles"]
    return dict(roles.get(role, roles["developer"]))


def _escalation_model(role: str) -> str | None:
    if role != "developer":
        return None
    return settings.developer_pro_model or settings.deep_seek_model or "deepseek-v4-pro"


def _capabilities(role: str) -> list[str]:
    """카드 badge용 짧은 capability — 도구·fresh·정책에서 파생(하드코딩 금지)."""
    names = _role_tool_names(role)
    if role == "reviewer":
        # read-only 스키마(런타임 강제) + fresh 컨텍스트로 독립 검증에 집중. Write/Bash 없음.
        return ["Fresh", "Read Only", "Verify"]
    caps: list[str] = []
    if not _read_only(role):
        caps.append("Write")
    if "bash" in names:
        caps.append("Bash")
    if "browser_check" in names:
        caps.append("Browser")
    if role in _FRESH_CONTEXT:
        caps.append("Fresh")
    if _read_only(role):
        caps.append("Read Only")
    return caps


def _base_agent(role: str) -> dict:
    pol = _policy(role)
    return {
        "id": role,
        "name": role.capitalize(),
        "display_name": _DISPLAY[role]["display_name"],
        "category": _DISPLAY[role]["category"],
        "icon": _DISPLAY[role]["icon"],
        "flavor": _DISPLAY[role]["flavor"],
        "description": _DISPLAY[role]["description"],
        "model": pol.get("model", ""),
        "escalation_model": _escalation_model(role),
        "thinking": bool(pol.get("thinking", False)),
        "reasoning_effort": pol.get("reasoning_effort", ""),
        "fresh_context": role in _FRESH_CONTEXT,
        "read_only": _read_only(role),
        "policy_note": _POLICY_NOTE.get(role, ""),
        "tools": _role_tool_names(role),
        "tool_count": len(_role_tool_names(role)),
        "capabilities": _capabilities(role),
        "prompt_source": f"docs/agents/{role}.md",
        "prompt_hash": _prompt_hash(role),
        "active": True,
    }


def agent_definitions() -> list[dict]:
    """main roster — 실제 runtime이 호출하는 role만. 활성 여부는 runtime 존재로 결정."""
    return [_base_agent(r) for r in MAIN_ROLES]


def internal_definitions() -> list[dict]:
    out: list[dict] = []
    for rid, meta in _INTERNAL.items():
        item = {
            "id": rid,
            "name": meta["name"],
            "display_name": meta["name"],
            "category": meta["category"],
            "icon": "system",
            "flavor": meta["flavor"],
            "description": meta["flavor"],
            "model": "",
            "thinking": False,
            "fresh_context": rid == "gate_recovery",
            "read_only": False,
            "tools": [],
            "tool_count": 0,
            "capabilities": [],
            "prompt_source": f"docs/agents/{rid}.md" if meta["prompt_available"] else "",
            "prompt_hash": _prompt_hash(rid) if meta["prompt_available"] else "",
            "active": False,
        }
        if rid == "gate_recovery":
            item["tools"] = [t["function"]["name"] for t in GATE_RECOVERY_TOOL_SCHEMAS]
            item["tool_count"] = len(item["tools"])
            item["read_only"] = False  # update_gates는 mutation이지만 파일 수정은 아님
            item["model"] = _policy("gate_recovery").get("model", "")
            item["thinking"] = bool(_policy("gate_recovery").get("thinking", False))
        if rid == "vision":
            item["model"] = settings.vision_model or "deepseek-v4-flash-vision-exp"
        out.append(item)
    return out


def agent_detail(role: str) -> dict | None:
    if role not in MAIN_ROLES:
        return None
    agent = _base_agent(role)
    agent["tool_details"] = [
        {
            "name": t["function"]["name"],
            "description": _TOOL_DESCRIPTIONS.get(
                t["function"]["name"], t["function"].get("description", "")),
            "approval_required": t["function"]["name"] in APPROVAL_REQUIRED,
        }
        for t in _ROLE_TOOLS[role]
    ]
    return agent


def agent_prompt(role: str) -> dict | None:
    """Base Role Prompt만 반환한다(동적 memory/skills/plan/user data는 절대 붙이지 않음)."""
    if role not in MAIN_ROLES and role != "gate_recovery":
        return None
    text = _prompt_text(role)
    if not text:
        return None
    return {
        "id": role,
        "prompt": text,
        "source": f"docs/agents/{role}.md",
        "hash": _prompt_hash(role),
    }


def with_live_status(agents: list[dict], status: dict | None) -> list[dict]:
    """runtime.get_status() 결과와 연결 — 실행 중인 role만 Working으로 표시한다.
    허구의 상태를 만들지 않는다: 실행 중이 아니면 idle/recent다."""
    running = bool(status and status.get("running"))
    role = (status or {}).get("role", "")
    activity = (status or {}).get("activity", "")
    for a in agents:
        if running and a["id"] == role:
            a["status"] = "working"
            a["activity"] = activity
        elif (not running) and a["id"] == role:
            a["status"] = "recent"
            a["activity"] = ""
        else:
            a["status"] = "idle"
            a["activity"] = ""
    return agents
