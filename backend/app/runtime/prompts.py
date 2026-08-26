"""시스템 프롬프트·컨텍스트 빌딩·이미지/출력 전처리 — agent.py에서 분리.

동작 변경 없이 구조만 이동했다. agent.py는 이 모듈을 re-export해 기존
A.<name> 인터페이스를 그대로 유지한다(completion_policy와 동일 패턴).
"""

import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any

from ..config import settings
from .. import skills as skills_lib
from . import tool_store

# Skill 선택 삽입 한도 — skill이 많아져도 system prompt가 폭증하지 않게 상위 N개만,
# 총 문자 예산 안에서 삽입한다. 관련 skill이 없으면 아무것도 넣지 않는다.
MAX_ACTIVE_SKILLS = 3
SKILL_CHAR_BUDGET = 6000


# repo 루트 = prompts.py(backend/app/runtime) 기준 parents[3]. docs·GLOBAL_MEMORY는 루트에 있다.
# (agent.py에서 이동 — 경로 기준 파일이 달라지면 parents[3]은 동일하게 repo 루트를 가리킨다.)
_REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = _REPO_ROOT / "docs" / "agents"
GLOBAL_MEMORY_PATH = _REPO_ROOT / "GLOBAL_MEMORY.md"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"  # backend/app/uploads(정상)


def _has_image(msg: dict) -> bool:
    content = msg.get("content", "")
    if isinstance(content, list):
        return any(isinstance(c, dict) and c.get("type") == "image_url" for c in content)
    return False


def _turn_has_image(history: list[dict]) -> bool:
    """이번 턴(가장 최근 user 메시지)에 이미지가 있는지. 세션 전체가 아니라 마지막 요청만 본다.
    한 번 이미지를 보낸 세션의 이후 텍스트 작업까지 vision으로 실행하던 문제를 막는다."""
    for m in reversed(history):
        if m.get("role") == "user":
            return _has_image(m)
    return False


def _to_data_uri_item(item: Any) -> Any:
    if isinstance(item, dict) and item.get("type") == "image_url":
        url = item.get("image_url", {}).get("url", "")
        if isinstance(url, str) and url.startswith("/uploads/"):
            name = url.split("/")[-1]
            path = UPLOADS_DIR / name
            if path.exists():
                mime = mimetypes.guess_type(str(path))[0] or "image/png"
                b64 = base64.b64encode(path.read_bytes()).decode()
                return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    return item

BASE_PROMPT = """당신은 FORGE 에이전틱 코딩 에이전트의 일부입니다. 아래 역할 지침을 따르며 로컬 코드베이스에서 작업합니다.

## 공통 원칙
- 응답은 한국어로 한다. **항상 존댓말(합니다·습니다체)로 쓴다.** 반말·음슴체를 쓰지 않는다.
- **짧고 단정한 문장 위주로 핵심만 전한다.** 전보체에 가깝게 — 한 문장 한 정보, 군더더기·수식어·배경 설명 없이. 한 것과 결과만. (예: "calc.py 생성했습니다. 테스트 통과했습니다." / "버그 3곳 수정했습니다.") 존댓말은 유지한다.
- 응답에 이모지와 이미지를 넣지 않는다.
- 긴 내용은 요점마다 줄을 나눠 읽기 쉽게 한다. 다만 길이를 위해 늘리지는 않는다.
- 코드를 추측하지 말고 파일을 읽어 확인한다.
- 목표에 필요한 최소한의 파일만 읽는다. 전수 탐색하지 말고, 충분히 파악되면 즉시 다음 단계로 넘어간다.
- 도구 호출 전에 진행 상황을 짧은 텍스트로 설명한다.
- 같은 도구를 같은 인자로 반복 호출하지 않는다.
- 로직(분기·루프·파서·문자열 매칭·경계값·money/보안 경로)을 만들거나 고치면, 통과 케이스가 아니라 **자기 로직을 깨는 테스트**를 쓴다. 부분매칭 대신 정확 일치, happy-path 대신 뒤집힌 케이스·빈 입력·경계값을 노린다. 자기가 떠올린 경우만 검증하면 자기 맹점을 그대로 물려받는다 — 실패를 유도하는 테스트가 진짜 검증이다.

## 환경
- 워크스페이스: 로컬 마운트 디렉터리
- 도구: read_file, list_dir, grep, write_file, edit_file, bash, ask_user, update_tasks, save_skill
- write_file/edit_file/bash/save_skill는 사용자 승인이 필요하다.
- 축적된 Skill이 있으면 관련 작업에서 우선 활용한다. 여러 단계로 성공했고 앞으로 반복될 절차라면 save_skill로 저장해 다음에 재사용한다.
- save_skill의 scope는 기본 project다. 프로젝트 특화 절차(그 저장소의 규약·빌드·구조)는 project로, 특정 파일명·경로·도메인에 묶이지 않고 여러 코드베이스에서 재사용 가능한 명백히 범용적인 절차만 global로 저장한다. 판단이 애매하면 project. 단순 메모나 일회성 해결은 Skill로 저장하지 않는다."""


def _compress_command_output(command: str, output: str) -> str | None:
    """명령 종류별 deterministic 압축(LLM-free). 성공이 구조적으로 명확한 출력만 강하게
    줄이고, 실패·불명확은 None을 반환해 기본 prune(에러 tail 보존)에 맡긴다.
    confidence-aware — 오류 분석 정보를 지우지 않는 것이 원칙(요청 22)."""
    cmd = (command or "").lower()
    if not output or len(output) < 800:
        return None  # 작은 출력은 그대로
    lines = [ln for ln in output.splitlines() if ln.strip()]
    # 테스트 — 전부 통과면 요약 한 줄, 실패가 있으면 원본 보존(None)
    if any(k in cmd for k in ("pytest", "npm test", "npm run test", "vitest", "go test")):
        has_fail = re.search(r"\b(\d+)\s+(failed|error)", output) or "FAILED" in output
        passed = re.search(r"\b(\d+)\s+passed", output)
        if passed and not has_fail:
            last = next((ln for ln in reversed(lines) if "passed" in ln), lines[-1])
            return f"[테스트 전부 통과] {last.strip()}"
        return None  # 실패 — traceback 보존
    # git status — 변경 목록만
    if "git status" in cmd and len(lines) > 15:
        changed = [ln for ln in lines if re.match(r"\s*[AMDR?]{1,2}\s", ln) or ln[:1] in "MADR?"]
        head_lines = changed[:30] if changed else lines[:30]
        extra = max(0, len(lines) - len(head_lines))
        return "[git status] " + f"{len(changed) or len(lines)}개 변경\n" + "\n".join(head_lines) + (f"\n... {extra}줄 생략 ..." if extra else "")
    return None


def _prune_tool_result(text: str, head: int = 1400, tail: int = 900) -> str:
    """모델에 보낼 도구 결과를 축약한다(model-free pruning).

    긴 read_file/bash/grep 결과가 매 스텝 컨텍스트에 누적돼 폭증하는 것을 막는다.
    앞·뒤를 보존하고 가운데를 생략하되, 오류/경고 라인은 함께 남긴다.
    축약 시 원본은 tool_store에 저장하고 result_id를 안내한다 — 모델이 더 필요하면
    read_tool_result로 원본을 조회할 수 있어, 공격적으로 줄여도 정보 손실이 복구 가능하다.
    UI 표시는 원본을 쓰고, 이 축약본은 모델 컨텍스트(all_messages)에만 쓴다.
    """
    if len(text) <= head + tail + 300:
        return text[:20_000]
    error_lines = [
        ln for ln in text.splitlines()
        if any(k in ln.lower() for k in ("error", "오류", "fail", "warning", "traceback", "exception"))
    ]
    try:
        rid = tool_store.save(text)
        ref = f" (전체 {len(text)}자 저장됨 · 더 필요하면 read_tool_result('{rid}'))"
    except Exception:
        ref = ""
    body = text[:head] + f"\n\n... {len(text) - head - tail}자 생략{ref} ...\n\n" + text[-tail:]
    if error_lines:
        body += "\n\n[주요 오류/경고 라인]\n" + "\n".join(error_lines[:20])
    return body


def _load_role(role: str) -> str:
    path = AGENTS_DIR / f"{role}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _load_global_memory() -> str:
    if GLOBAL_MEMORY_PATH.exists():
        return GLOBAL_MEMORY_PATH.read_text(encoding="utf-8")
    return ""


def _load_room_memory(workspace: str) -> str:
    path = Path(workspace) / "ROOM_MEMORY.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _skill_terms(text: str) -> list[str]:
    """매칭용 키워드: 영문/숫자 토큰 + 2자 이상 한글 런. 소문자화."""
    return [t for t in re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", text.lower())]


def _select_skills(workspace: str, query: str) -> str:
    """요청과 관련된 skill만 골라 삽입한다(selective retrieval, vector DB 없음).

    파일을 로컬에서 읽는 건 무료다 — 비용은 '프롬프트에 들어가는 것'뿐이므로,
    모든 skill을 읽어 요청 키워드와의 겹침으로 점수를 매기고 상위 N개만,
    문자 예산 안에서 삽입한다. 제목 일치는 가중치 3, 본문 일치는 1.
    한글 교착어를 흡수하려고 부분 문자열 포함으로 매칭한다.
    curated+learned(global) + project 3계층을 병합해 대상으로 삼는다(같은 이름은
    project 우선). 점수가 같으면 project skill을 먼저 넣는다(명시적 local 우선).
    관련 skill이 없으면 빈 문자열(아무것도 삽입하지 않음)."""
    if settings.skills_off:  # 실험용: skill 주입 전면 비활성(A/B 측정)
        return ""
    terms = set(_skill_terms(query))
    if not terms:
        return ""
    scored: list[tuple[int, int, str, str]] = []  # (score, project우선, name, body)
    for sk in skills_lib.iter_skills(workspace):
        stem, body = sk["name"], sk["content"]
        stem_l = stem.lower()
        body_l = body.lower()
        score = sum(3 for t in terms if t in stem_l) + sum(1 for t in terms if t in body_l)
        if score > 0:
            proj_first = 0 if sk.get("scope") == "project" else 1
            scored.append((score, proj_first, stem, body))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))  # 점수↓ → project 먼저 → 이름
    blocks: list[str] = []
    used = 0
    for _score, _pf, stem, body in scored[:MAX_ACTIVE_SKILLS]:
        block = f"### skill: {stem}\n{body}"
        if used + len(block) > SKILL_CHAR_BUDGET:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _est_tokens(text: str) -> int:
    """토큰 근사치 — 전송 전 영역별 비중 파악용(실측은 provider usage). ASCII는 ~4자/토큰,
    비ASCII(한글 등)는 ~1.5자/토큰으로 어림한다. 절대값보다 영역 간 상대 비교가 목적."""
    if not text:
        return 0
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return ascii_n // 4 + (len(text) - ascii_n) * 2 // 3 + 1


def _stable_prefix(role: str) -> str:
    """호출마다 변하지 않는 프리픽스: BASE_PROMPT + role 지침.

    prompt cache는 요청 토큰 프리픽스에 걸리므로, 이 부분을 맨 앞에 고정하면
    같은 role의 모든 호출(스텝·태스크·세션 간)이 이 프리픽스를 캐시 히트한다.
    memory/skills 같은 동적 부분은 뒤에 붙인다."""
    return BASE_PROMPT + "\n\n" + _load_role(role)


def _stable_prefix_hash(role: str) -> str:
    return hashlib.sha256(_stable_prefix(role).encode("utf-8")).hexdigest()[:12]


def _system_for(role: str, room_memory: str = "", skills: str = "", plan: str = "",
                requirements: str = "") -> str:
    # 안정 프리픽스(BASE+role)를 먼저, 동적 tail(memory→skills→plan)을 뒤에 둔다.
    parts = [_stable_prefix(role)]
    global_mem = _load_global_memory()
    if global_mem:
        parts.append("\n\n## 전역 메모리 (GLOBAL_MEMORY.md)\n" + global_mem)
    if room_memory:
        # 메모리는 보조 정보다 — 현재 코드가 최종 권위다. 이 순서를 명시하지 않으면
        # 과거에 적립된(그리고 그 사이 바뀐) 사실을 현재 구현보다 우선해 판단한다.
        parts.append(
            "\n\n## 방 메모리 (ROOM_MEMORY.md)\n"
            "이것은 검증된 작업에서 축적한 **보조 정보**다. 현재 소스·설정과 충돌하면 "
            "**반드시 현재 소스를 따른다.** 메모리에 적힌 내용도 작업 전에 실제 파일로 "
            "확인한다.\n\n" + room_memory)
    if skills:
        parts.append(
            "\n\n## 축적된 Skill (재사용 가능한 해결 절차)\n"
            "관련 작업이면 아래 절차를 우선 활용하라.\n" + skills
        )
    if plan:
        parts.append(
            "\n\n## 외부 계획 (Planner가 수립 — 순서와 완료 조건을 따른다)\n" + plan
        )
    if requirements:
        parts.append(
            "\n\n## 사용자 요구사항 (id는 acceptance gate 연결용)\n"
            "update_gates로 gate를 등록할 때 각 gate의 requirement_id에 해당 id를 넣어라. "
            "통과한 gate가 연결되지 않은 요구사항은 미검증으로 남아 완료가 강등된다.\n"
            + requirements
        )
    return "".join(parts)


def _planner_context(all_messages: list[dict], max_msgs: int = 8) -> list[dict]:
    """Planner에게 주는 축소 컨텍스트 — 전체 재전송 비용을 피하려고 최근 메시지만 준다.
    (과거 planner가 컨텍스트 전체를 재전송해 비용 73%를 차지했던 문제의 재발 방지)

    도구 이력(tool_calls / role:tool)은 제외한다. 이유가 둘이다.
    1) 최근 N개를 그냥 자르면 슬라이스가 orphan `tool` 메시지로 시작해 DeepSeek이 400을
       낸다("tool must follow tool_calls") — 실제로 planner를 죽인 버그. read 루프로 tool
       메시지가 많이 쌓인 세션에서 재현된다.
    2) Planner는 계획만 세우므로 과거 도구 호출·결과가 필요 없다. user 요청과 assistant
       텍스트만으로 충분하다.
    """
    clean: list[dict] = []
    for m in all_messages:
        role = m.get("role")
        if role == "tool":
            continue  # 도구 결과 — planner에 불필요, orphan이면 400 유발
        if role == "assistant" and m.get("tool_calls"):
            # 도구 호출 어시스턴트 — tool_calls를 벗기고 텍스트만(있을 때) 남긴다.
            if m.get("content"):
                clean.append({"role": "assistant", "content": m["content"]})
            continue
        clean.append(m)
    return clean[-max_msgs:]


def _reviewer_context(all_messages: list[dict], plan: str) -> list[dict]:
    """Reviewer에게 주는 fresh·minimal 컨텍스트 — Developer의 작업 기록을 주지 않는다.

    두 가지 이유가 있고, 두 번째가 본질이다.
    1) 비용 — 전체 transcript 재전송은 planner에서 이미 비용 73%를 만든 패턴이다.
    2) **독립성** — Developer의 추론을 읽은 리뷰어는 그 프레이밍과 맹점을 그대로 물려받는다.
       "왜 이렇게 했는지"를 먼저 읽으면 결과가 아니라 변명을 검토하게 된다. 리뷰어의
       가치는 결과물을 처음 보는 눈으로 본다는 것뿐이다(self-grading 방지).

    그래서 원 요청 + 완료 조건(plan)만 주고, 변경은 git diff로 직접 확인하게 한다
    (reviewer.md 검증 순서 1번이 이미 그렇게 규정한다).
    """
    msgs = [m for m in all_messages if m.get("role") == "user"][-3:]
    if plan:
        msgs.append({"role": "assistant", "content": "계획(완료 조건):\n" + plan})
    msgs.append({"role": "user", "content":
                 "위 요청과 완료 조건을 기준으로 방금 끝난 작업을 독립 검증하세요. "
                 "Developer의 작업 기록은 주어지지 않습니다 — `git diff`로 실제 변경을 직접 "
                 "확인하고, 테스트·빌드를 실제로 실행해 판정하세요."})
    return msgs


def build_gate_recovery_context(goal: str, files_changed: list, tasks: list) -> list[dict]:
    """복구 턴에 주는 최소 컨텍스트 — Developer의 거대한 transcript를 재전송하지 않는다.

    gate를 쓰는 데 필요한 것은 "사용자가 뭘 요구했나"와 "무엇이 바뀌었나"뿐이다.
    전체 히스토리를 다시 보내면 gate 없는 run마다 컨텍스트 비용이 두 배가 된다.
    """
    files = ", ".join(str(f) for f in list(files_changed)[:20]) or "(없음)"
    titles = [t.get("title", "") for t in (tasks or []) if t.get("title")][:10]
    lines = [f"사용자 요청:\n{(goal or '').strip()[:1200]}",
             f"\n이번 작업에서 변경된 파일: {files}"]
    if titles:
        lines.append("수행한 작업 항목:\n" + "\n".join(f"- {t}" for t in titles))
    lines.append("\n구현은 끝났다. 위 사용자 요청을 검증할 acceptance gate를 "
                 "update_gates로 등록하라. 코드는 고치지 않는다.")
    return [{"role": "user", "content": "\n".join(lines)}]


def _requirements_block(requirements) -> str:
    """Task IR requirement를 gate 연결용 짧은 블록으로 만든다(순수 함수).

    모델은 requirement id(R1..)를 알 방법이 없다 — Task IR은 이벤트로만 나가고 프롬프트에는
    없었다. id를 안 주면 gate의 requirement_id가 영원히 비고, traceability는 모든 요구사항을
    미검증으로 봐 완료가 매번 강등된다(지표가 노이즈가 된다). 그래서 id를 명시적으로 준다.
    reqs가 없으면 빈 문자열 — 호출측이 그대로 넘겨도 프롬프트가 바뀌지 않는다(Task IR off).
    """
    lines = [f"- {r['id']}: {str(r.get('text', '')).strip()[:200]}"
             for r in (requirements or [])
             if isinstance(r, dict) and r.get("id") and str(r.get("text", "")).strip()]
    return "\n".join(lines)


def _untraced_requirements(requirements, trace) -> list[dict]:
    """traceability가 미검증으로 표시한 requirement id를 보고용 {id,text}로 되돌린다.

    "일부 요구사항 미검증"만 말하고 무엇이 빠졌는지 안 알려주면 사용자가 확인할 방법이 없다.
    """
    ids = (trace or {}).get("unverified_ids") or []
    if not ids:
        return []
    text = {str(r["id"]): str(r.get("text", "")).strip()
            for r in (requirements or []) if isinstance(r, dict) and r.get("id")}
    return [{"id": str(i), "text": text.get(str(i), "")} for i in ids]


def _last_assistant_text(messages: list[dict]) -> str:
    """마지막 assistant 텍스트(계획·리뷰 판정 추출용)."""
    for m in reversed(messages):
        if m.get("role") == "assistant":
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _plan_to_tasks(plan: str, limit: int = 8) -> list[dict]:
    """Planner 계획의 번호 목록(1. / 2) …)을 칸반 태스크로 뽑는다.

    모델이 update_tasks를 안 불러도 칸반이 채워지게 하는 강제 장치(multi 모드 전용).
    '## 완료 조건' 뒤의 번호까지 섞여 들어오는 것을 막으려 상위 limit개만, 계획 본문에서만
    추출한다(완료 조건 섹션은 잘라낸다)."""
    body = re.split(r"##\s*완료\s*조건", plan or "", maxsplit=1)[0]
    steps = re.findall(r"^\s*\d+[.)]\s+(.+)$", body, re.MULTILINE)
    out, seen = [], set()
    for s in steps:
        title = s.strip().rstrip(".")[:80]
        key = title.lower()
        if title and key not in seen:
            seen.add(key)
            out.append({"title": title, "status": "todo"})
        if len(out) >= limit:
            break
    return out


def _format_question(text: str, line_len: int = 56) -> str:
    """질문 텍스트를 문장 단위로 줄바꿈해 팝업 가독성을 높인다.

    모델이 보낸 질문은 보통 한 줄로 길게 온다. 문장 경계(。.!?) 뒤와,
    한 줄이 지나치게 길어지면 그 지점에서 줄바꿈을 넣어 읽기 쉽게 만든다.
    이미 줄바꿈(모델이 구조화)이 있으면 그대로 둔다."""
    if not text:
        return text
    if "\n" in text:
        return text
    import re
    sentences = re.split(r"(?<=[。.!?])\s+", text.strip())
    out: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) > line_len:
            out.append(buf)
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf:
        out.append(buf)
    return "\n".join(out)


# auto 모드의 multi 전환 기준 — 요청 특성이 복잡 작업으로 보이면 Planner가 선행한다.
_COMPLEX_KEYWORDS = (
    "설계", "리팩토링", "리팩터링", "아키텍처", "마이그레이션", "전체",
    "여러 모듈", "다중 모듈", "시스템 전반", "모노레포", "대규모",
)


def _estimate_complexity(goal: str, all_messages: list[dict]) -> str:
    """simple | complex — 세션의 에이전트 모드가 auto일 때 single/multi를 가른다."""
    text = goal or ""
    if any(k in text for k in _COMPLEX_KEYWORDS):
        return "complex"
    if len(text) > 300:  # 상세한 요구사항 = 다단계 작업 가능성
        return "complex"
    user_msgs = [m for m in all_messages if m.get("role") == "user"]
    if len(user_msgs) >= 5:  # 이미 여러 단계를 밟은 긴 작업
        return "complex"
    return "simple"


