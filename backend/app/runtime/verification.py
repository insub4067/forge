"""Acceptance Gate 실행·보고 — agent.py에서 분리한 2차 책임 단위.

completion_policy가 '무엇을 완료로 볼 것인가'(정책)라면, 여기는 '각 gate의 verification_method를
실제 실행해 증거로 판정'(실행)이다. 인스턴스 상태(self)에 의존하지 않으므로 모듈 함수로 두고,
agent.py는 thin delegator로 기존 이름·동작을 유지한다(외부 인터페이스 불변). agent를 import하지
않아 순환 없음.
"""
import asyncio
import json
import os
from typing import Awaitable, Callable

from ..db import store
from ..sandbox.executor import DockerSandbox

EventSink = Callable[[dict], Awaitable[None]]


# gate 명령이 rc!=0로 실패했을 때, 그 실패가 '구현 오류'가 아니라 '명령 자체의 인프라
# 오류'(문법·실행불가·quoting)임을 알리는 신호. 모델이 verification 명령을 직접 작성하므로
# python3 -c에 여러 줄을 리터럴 \n으로 넣어 SyntaxError를 내는 등 명령 결함으로 실패하는 일이
# 잦다. 그 경우 정답 코드가 gate 결함 때문에 verification_failed로 과차단된다.
#
# **중요(false_completion 방지)**: 파싱 오류(SyntaxError 등)는 gate 명령 자체(python3 -c/stdin
# 인라인 스크립트)에서 날 수도 있고, **검사 대상 코드**(워크스페이스 .py 파일)에서 날 수도 있다.
# 후자는 진짜 구현 실패다. 이를 infra로 오분류하면 깨진 코드가 completed_unverified로 새어
# false_completion이 는다. 그래서 파싱 오류는 traceback이 `<string>`/`<stdin>`(=명령의 인라인
# 스크립트)일 때만 infra로 보고, 워크스페이스 파일 경로면 failed로 남긴다.
_GATE_SHELL_SIGNALS = (
    "command not found",              # 셸이 실행 파일을 못 찾음 — 정상 코드 실행에선 안 남
    "syntax error near",              # bash 파스 오류(syntax error near unexpected token)
    "unexpected EOF while looking",   # bash quoting 미완결(...looking for matching quote)
    "can't open file",                # python3 <script>가 스크립트 파일을 못 엶(명령 인자 오류)
)
_GATE_PARSE_SIGNALS = (
    "SyntaxError",              # python -c에 여러 줄을 리터럴 \n으로 넣어 개행이 안 풀림
    "IndentationError",
    "invalid syntax",
    "unexpected EOF while parsing",   # python 인라인 스크립트 미완결
)


def _gate_infra_error(rc: int, output: str) -> bool:
    """gate 명령이 실패(rc!=0)했을 때, 그 실패가 구현 실패가 아니라 명령 자체의 인프라
    오류인지 판정한다. rc==0(명령이 정상 실행됨)에는 적용하지 않는다.

    - 셸 레벨 오류(command not found / bash 파스)는 정상 코드 실행에서 나올 수 없으므로 infra.
    - 파싱 오류(SyntaxError 등)는 traceback이 `<string>`/`<stdin>`(명령의 인라인 스크립트)일
      때만 infra. 워크스페이스 .py 파일에서 난 파싱 오류는 검사 대상 코드의 결함(failed 유지).
    """
    if rc == 0:
        return False
    if any(sig in output for sig in _GATE_SHELL_SIGNALS):
        return True
    if ("<string>" in output or "<stdin>" in output) \
            and any(sig in output for sig in _GATE_PARSE_SIGNALS):
        return True
    return False


def classify_gate(rc: int, output: str, expected: str) -> tuple[str, str]:
    """gate 명령 실행 결과를 verdict로 판정한다(순수 함수 — 무LLM 결정적 테스트 대상).

    passed      — exit 0 AND 기대 문자열이 출력에 존재
    unavailable — 통과 증거 부족(expected 없음) 또는 명령 자체의 인프라 오류(GATE_EXECUTION_ERROR).
                  둘 다 "검증 못 함"이라 완료 정책상 completed_unverified로 안전 강등된다
                  (완료 주장 안 함 → false_completion 안 늘림).
    failed      — 명령은 정상 실행됐으나 기대 미충족/로직 실패(AssertionError·기대값 불일치 등).
                  검증 약화 금지 invariant를 지키려 인프라-오류 신호가 명확할 때만 unavailable로 뺀다.
    """
    if rc == 0 and expected and expected in output:
        return "passed", ""
    if rc == 0 and not expected:
        # exit 0만으로는 기능 충족을 증명하지 못한다 — PASS 오판 금지.
        return "unavailable", "expected_result 없음 — 통과 증거로 불충분"
    if _gate_infra_error(rc, output):
        return "unavailable", (
            f"GATE_EXECUTION_ERROR: 명령 인프라 오류(exit {rc}) — 검증 불가, 구현 실패 아님")
    reason = f"exit {rc}" + (f", 기대 결과 미발견: {expected[:80]}" if expected else "")
    return "failed", reason


async def _worktree_git_hash(ws: str):
    """워크스페이스 현재 변경 상태 해시(porcelain + diff HEAD). git repo 아니거나 실패면 None.
    gate 검증 명령 전후 비교로 '검증이 대상 소스를 바꿨는지'를 잡는다(P0-B: self-grading 우회 차단)."""
    import hashlib

    async def _g(*args, timeout=15):
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", ws, *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, out.decode(errors="replace")
        except Exception:
            return 1, ""

    if not ws:
        return None
    rc, inside = await _g("rev-parse", "--is-inside-work-tree", timeout=8)
    if rc != 0 or "true" not in inside:
        return None
    _, porc = await _g("status", "--porcelain")
    _, diff = await _g("diff", "HEAD")
    return hashlib.sha1((porc + "\x00" + diff).encode("utf-8", "replace")).hexdigest()


async def _git_ws(ws: str, *args, timeout=30):
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", ws, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="replace")
    except Exception:
        return 1, ""


async def make_prechange_worktree(ws: str):
    """HEAD(이번 run 변경 이전 커밋) 워크트리를 임시 생성 — 게이트 명령을 여기서 먼저 돌려
    'trivial 게이트'(변경 전에도 통과 = 판별력 없음)를 잡는다(P0-A). live 워크스페이스는 절대
    건드리지 않는다(격리 워크트리). git repo 아니거나 실패면 None(probe 생략 → 강등 안 함)."""
    import tempfile
    if not ws:
        return None
    rc, inside = await _git_ws(ws, "rev-parse", "--is-inside-work-tree", timeout=8)
    if rc != 0 or "true" not in inside:
        return None
    tmp = tempfile.mkdtemp(prefix="forge-prechange-")
    rc, _ = await _git_ws(ws, "worktree", "add", "--detach", tmp, "HEAD", timeout=30)
    if rc != 0:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return tmp


async def remove_prechange_worktree(ws: str, tmp) -> None:
    """probe 워크트리 정리 — 등록 해제 + 디렉터리 삭제. 실패해도 조용히 넘어간다."""
    if not tmp:
        return
    await _git_ws(ws, "worktree", "remove", "--force", tmp, timeout=20)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


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

    # P0-A: 변경 이전(HEAD) 코드에서 게이트를 먼저 실행해 'trivial 게이트'(변경 없이도 통과 =
    # 판별력 없음)를 잡는다. 격리 워크트리 — live 워크스페이스는 건드리지 않는다.
    probe_dir = await make_prechange_worktree(ws)
    probe_sandbox = DockerSandbox(workspace=probe_dir) if probe_dir else None

    async def _probe(command: str, timeout: int = 120):
        if not probe_sandbox:
            return None
        try:
            return await probe_sandbox.run_verify(command, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    labels: list[str] = []
    resolved: list[str] = []
    try:
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
          # P0-A: 변경 이전(HEAD) 코드에서 먼저 실행 — 여기서도 passed면 이 게이트는 변경을 판별하지
          # 못하는 trivial 게이트다(예: echo hello/expected hello). probe 불가(None)면 판정 안 함.
          probe_res = await _probe(method)
          trivial = probe_res is not None and classify_gate(probe_res[0], probe_res[1], expected)[0] == "passed"

          _wt_before = await _worktree_git_hash(ws)
          rc, out = await _sh(method, ws)
          _wt_after = await _worktree_git_hash(ws)
          evidence = json.dumps({
              "command": method, "exit_code": rc,
              "output_tail": out[-1500:], "expected": expected, "gate_validity": "trivial" if trivial else "valid",
          }, ensure_ascii=False)
          # 판정 우선순위: trivial → 검증이 대상 변경(P0-B) → 정상 classify.
          if trivial:
              verdict, reason = "unavailable", "trivial 게이트 — 변경 이전 코드에서도 통과(판별력 없음). 검증으로 인정하지 않는다"
          elif (_wt_before is not None and _wt_after is not None and _wt_before != _wt_after):
              # P0-B: 검증 명령이 워크스페이스 소스를 바꿨으면(게이트 A가 게이트 B의 통과 조건을 만드는
              # 자기충족 경로) passed로 인정하지 않고 unavailable로 강등한다 — 검증은 대상을 관찰만 해야 한다.
              verdict, reason = "unavailable", "검증 명령이 워크스페이스를 변경함 — 대상을 관찰만 해야 하므로 판정 보류"
          else:
              verdict, reason = classify_gate(rc, out, expected)
          await store.save_gate_result(session_id, g["id"], verdict, evidence, reason)
          labels.append(f"{g['title']}({verdict})")
          resolved.append(verdict)
          await send("gates_update", {"gates": await store.list_gates(session_id)})

    finally:
      await remove_prechange_worktree(ws, probe_dir)
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


# 검증 실행 전 워크스페이스 스냅샷/클린업 — agent.py에서 분리(모듈 함수, 인스턴스 상태 무관).
# 무겁고/건드리면 안 되는 디렉터리(.git/.venv/node_modules 등)는 제외 — 정리 대상도 아니다.
VERIFY_SNAPSHOT_SKIP = {".git", ".venv", "node_modules",
                        "__pycache__", ".pytest_cache", ".mypy_cache"}


def verify_snapshot(ws: str) -> set:
    """검증 실행 직전 워크스페이스 파일 집합 스냅샷."""
    seen = set()
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in VERIFY_SNAPSHOT_SKIP]
        for f in files:
            seen.add(os.path.join(root, f))
    return seen


def verify_cleanup(ws: str, before: set) -> None:
    """검증이 **새로 만든** 파일만 제거해 워크스페이스를 검증 전 상태로 되돌린다.
    스냅샷에 이미 있던 파일(구현 산출물)은 건드리지 않는다 — 판정에는 관여 안 함
    (state/report 확정 후 실행). 실제 실패 탐지도 약화되지 않는다(파일만 청소)."""
    for path in verify_snapshot(ws) - before:
        try:
            os.remove(path)
        except OSError:  # 이미 없거나 권한 문제면 무시 — 청소 실패가 결과를 바꾸면 안 됨
            pass
