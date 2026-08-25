"""Acceptance Gate 실행·보고 — agent.py에서 분리한 2차 책임 단위.

completion_policy가 '무엇을 완료로 볼 것인가'(정책)라면, 여기는 '각 gate의 verification_method를
실제 실행해 증거로 판정'(실행)이다. 인스턴스 상태(self)에 의존하지 않으므로 모듈 함수로 두고,
agent.py는 thin delegator로 기존 이름·동작을 유지한다(외부 인터페이스 불변). agent를 import하지
않아 순환 없음.
"""
import asyncio
import json
from typing import Awaitable, Callable

from ..db import store
from ..sandbox.executor import DockerSandbox

EventSink = Callable[[dict], Awaitable[None]]


async def verify_gates(ws: str, session_id: str, send: EventSink) -> tuple[str, str]:
    """각 gate의 verification_method를 실제 실행해 (state, report) 반환.

    passed는 오직 (exit 0 AND expected_result가 출력에 존재)일 때만. 모델이 passed라 주장해도
    재실행해 덮어쓴다(self-grading·evidence 위조 방지). 집계: failed>partial>passed>unavailable>none.
    gate 검증은 bash 도구와 동일 안전 경계(DockerSandbox.run_verify)로 실행한다.
    """
    if not session_id:
        return "none", ""
    gates = await store.list_gates(session_id)
    if not gates:
        return "none", ""

    sandbox = DockerSandbox(workspace=ws)

    async def _sh(command: str, cwd: str = "", timeout: int = 120) -> tuple[int, str]:
        try:
            return await sandbox.run_verify(command, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            return -1, f"실행 오류: {err}"

    labels: list[str] = []
    resolved: list[str] = []
    for g in gates:
        status = g.get("status", "pending")
        # blocked/abandoned는 모델이 사유와 함께 남긴 정직한 미완료 — 강제 실행하지 않는다.
        if status in ("blocked", "abandoned"):
            labels.append(f"{g['title']}({status})")
            resolved.append(status)
            continue
        method = (g.get("verification_method") or "").strip()
        expected = (g.get("expected_result") or "").strip()
        if not method:
            # 실행 가능한 검증이 없으면 passed로 만들지 않고 unavailable로 확정(숨기지 않음).
            await store.save_gate_result(
                session_id, g["id"], "unavailable", "{}",
                g.get("failure_reason") or "검증 방법 없음 — 실행 가능한 verification_method가 없다")
            labels.append(f"{g['title']}(unavailable)")
            resolved.append("unavailable")
            await send("gates_update", {"gates": await store.list_gates(session_id)})
            continue
        rc, out = await _sh(method, ws)
        evidence = json.dumps({
            "command": method, "exit_code": rc,
            "output_tail": out[-1500:], "expected": expected,
        }, ensure_ascii=False)
        if rc == 0 and expected and expected in out:
            verdict, reason = "passed", ""
        elif rc == 0 and not expected:
            # exit 0만으로는 기능 충족을 증명하지 못한다 — PASS 오판 금지.
            verdict, reason = "unavailable", "expected_result 없음 — 통과 증거로 불충분"
        else:
            verdict = "failed"
            reason = f"exit {rc}" + (f", 기대 결과 미발견: {expected[:80]}" if expected else "")
        await store.save_gate_result(session_id, g["id"], verdict, evidence, reason)
        labels.append(f"{g['title']}({verdict})")
        resolved.append(verdict)
        await send("gates_update", {"gates": await store.list_gates(session_id)})

    report = "요구사항 게이트 검증: " + ", ".join(labels)
    if "failed" in resolved:
        return "failed", report
    if all(s == "passed" for s in resolved):
        return "passed", report
    if any(s == "passed" for s in resolved):
        return "partial", report
    return "unavailable", report


async def gates_report(session_id: str) -> str:
    """미완료 gate를 최종 결과에 남긴다 — 조용한 생략(honest failure 위반) 금지."""
    if not session_id:
        return ""
    gates = await store.list_gates(session_id)
    if not gates:
        return ""
    marks = {"passed": "✓", "failed": "✗", "working": "○", "pending": "○",
             "unavailable": "!", "blocked": "!", "abandoned": "–"}
    lines = [f"요구사항 {len(gates)}"]
    for g in gates:
        s = g.get("status", "pending")
        line = f"{marks.get(s, '?')} {g['title']}"
        if s == "unavailable":
            line += f" — {g.get('failure_reason') or '검증 방법 없음'}"
        elif s == "blocked":
            line += f" — 차단: {g.get('failure_reason') or '이유 없음'}"
        elif s == "abandoned":
            line += f" — 포기: {g.get('failure_reason') or '이유 없음'}"
        elif s == "failed":
            line += f" — 실패: {g.get('failure_reason') or ''}"
        elif s in ("working", "pending"):
            line += " — 검증 중"
        lines.append(line)
    for g in gates:
        if g.get("status") in ("failed", "blocked") and (g.get("failure_reason") or g.get("evidence")):
            lines.append(f"  Gate: {g['title']}")
            lines.append(f"  Status: {g.get('status')}")
            if g.get("failure_reason"):
                lines.append(f"  Reason: {g.get('failure_reason')}")
            if g.get("evidence"):
                lines.append(f"  Evidence: {str(g.get('evidence'))[:300]}")
    return "\n".join(lines)
