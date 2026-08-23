"""Continual Harness Refinement — 근거 수집과 후보 생성(순수 함수, LLM 없음).

실행 경험을 evidence로 모아 작은 durable improvement 후보(RefinementCandidate)를 만든다.
여기서는 **후보를 만들 뿐 적용하지 않는다** — 적용은 사용자 승인 뒤 별도 단계다.

원칙:
- LLM-as-judge 금지. 후보 생성은 eventlog의 결정적 사실(검증 실패 리포트)만 본다.
- 1회 성공/실패로 승격 금지. 서로 다른 run에서 같은 실패 서명이 MIN_EVIDENCE_RUNS회
  이상 관측돼야 후보가 된다.
- Base Prompt는 건드리지 않는다. 후보 대상은 Project/Learned Skill·supplement뿐이다.
"""
import re

MIN_EVIDENCE_RUNS = 2  # 서로 다른 run에서 같은 실패가 이만큼 반복돼야 후보 생성


def _label_of(report: str) -> str:
    """검증 리포트 첫 줄의 [label] — 어떤 check가 깨졌는지."""
    m = re.match(r"\s*\[([^\]]{1,60})\]", report or "")
    return m.group(1).strip() if m else "verification"


def failure_signature(report: str) -> str:
    """실패 리포트를 재발 비교용 서명으로 정규화한다.

    경로·줄번호·시간처럼 run마다 달라지는 값을 지워야 '같은 실패'를 셀 수 있다.
    """
    label = _label_of(report)
    line = ""
    for ln in (report or "").splitlines():
        t = ln.strip()
        if not t or t.startswith("["):
            continue
        if re.search(r"error|Error|ERROR|assert|Assertion|failed|FAIL|Traceback", t):
            line = t
            break
    if not line:
        lines = [x.strip() for x in (report or "").splitlines() if x.strip()]
        line = lines[-1] if lines else ""
    line = re.sub(r"/\S*/", "", line)      # 절대경로 → 파일명만
    line = re.sub(r"\d+", "#", line)        # 줄번호·개수 등 변동값
    line = re.sub(r"\s+", " ", line).strip()
    return f"{label}: {line}"[:160]


def scan_failures(events: list[dict]) -> list[dict]:
    """eventlog 이벤트 열(오래된 순)에서 run 단위 검증 실패 목록을 뽑는다.

    FORGE의 session은 오래 사는 방이므로 session_id로는 run을 구분할 수 없다.
    done 이벤트를 경계로 세션별 run 번호를 매겨 "서로 다른 run"을 센다.
    반환: [{"run": "<session_id>#<n>", "signature": ...}]
    """
    run_no: dict[str, int] = {}
    out: list[dict] = []
    for ev in events:
        sid = ev.get("session_id") or ""
        n = run_no.get(sid, 0)
        etype = ev.get("type")
        if etype == "verify_failed":
            report = (ev.get("data") or {}).get("report", "")
            out.append({"run": f"{sid}#{n}", "signature": failure_signature(report),
                        "report": report})
        elif etype == "done":
            run_no[sid] = n + 1
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "verification"


def target_for(report: str) -> str:
    """이 실패에 대응하는 skill 이름 — before 스냅샷 조회와 후보 생성이 같은 이름을 쓴다."""
    return f"verify-{_slug(_label_of(report))}"


def propose(current_run: str, failures: list[dict], before: str = "",
            evidence: dict | None = None) -> dict | None:
    """이번 run의 실패 서명이 다른 run에서도 반복됐으면 후보를 만든다. 아니면 None.

    current_run: scan_failures의 run 키(이번 run).
    before: 대상 skill의 현재 내용(없으면 "") — rollback을 위한 before 스냅샷.
    """
    mine = [f for f in failures if f["run"] == current_run]
    if not mine:
        return None
    sig = mine[-1]["signature"]
    runs = sorted({f["run"] for f in failures if f["signature"] == sig})
    if len(runs) < MIN_EVIDENCE_RUNS:
        return None

    label = _label_of(mine[-1]["report"])
    target = target_for(mine[-1]["report"])
    change = (
        f"# {label} 검증 실패 재발 방지\n\n"
        f"## 관측\n서로 다른 run {len(runs)}회에서 같은 검증 실패가 반복됐다.\n\n"
        f"## 실패 서명\n```\n{sig}\n```\n\n"
        "## 절차\n"
        f"1. 완료를 보고하기 전에 `{label}`을 직접 실행한다.\n"
        "2. 위 서명과 같은 오류가 나오면 원인을 먼저 고치고 다시 실행한다.\n"
        "3. 통과를 확인한 뒤에만 완료로 보고한다.\n"
    )
    return {
        "type": "skill",
        "scope": "project",          # global 오염 방지 — 승격은 별도 판단
        "target": target,
        "proposed_change": change,
        "before_text": before,
        "after_text": change if not before else before.rstrip() + "\n\n" + change,
        "evidence_runs": runs,
        "failure_pattern": sig,
        "expected_effect": f"{label} 동일 실패 재발 감소 — 검증 통과 전 완료 보고 방지",
        "evidence": evidence or {},
    }
