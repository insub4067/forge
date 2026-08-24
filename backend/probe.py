"""FORGE 자기 핵심 경로 프로브 — 실행 중인 서버 대상 end-to-end 회귀 검사.

단위 테스트(pytest)는 함수를 본다. 하지만 오늘 나온 버그들은 전부 **경로 이음새**에서
났다(요청→핸들러→store→모델→응답). 이미지 미전달, 워크스페이스 유령 id, 압축 유실,
grep/list_dir 폭주 — 하나같이 함수는 맞는데 이음새가 틀렸다. 이 프로브는 내가 손으로
반복하던 격리 워크스페이스 검사를 한 명령으로 만든 것이다.

사용:
    ./.venv/bin/python probe.py            # 무비용 이음새 검사만(빠름)
    ./.venv/bin/python probe.py --full     # + 실제 LLM 코드 작업 1회(비용·비결정적)

무LLM 검사는 서버만 있으면 되고 돈이 안 든다. --full은 실제 세션을 돌려 gate·완료
보고·프로젝트 메모리·자동 커밋까지 확인한다(격리 워크스페이스, 끝나면 정리).
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = os.environ.get("FORGE_URL", "http://127.0.0.1:8790")


class ProbeFail(Exception):
    pass


def _req(method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


def _ok(name):
    print(f"  ✓ {name}")


# ─── 무LLM 이음새 검사 ───────────────────────────────────────────────

def check_health():
    try:
        st, _ = _req("GET", "/api/health", timeout=5)
    except Exception as e:
        raise ProbeFail(f"서버에 연결할 수 없습니다({BASE}): {e}")
    if st != 200:
        raise ProbeFail(f"health {st}")
    _ok("서버 health 200")


def check_server_stays_responsive_under_listdir():
    """홈 디렉터리 list_dir이 서버를 먹통으로 만들지 않는다(grep/list_dir 폭주 회귀).

    예전엔 워크스페이스가 홈이면 동기 재귀가 이벤트 루프를 몇 분간 막았다. 지금은 상한·
    오프로드가 있어야 한다. list_dir을 직접 못 부르니, 그 사이 health가 빠른지로 확인한다.
    (도구 자체 상한은 test_grep_bounds.py가 결정적으로 고정한다 — 여기선 라이브 응답성만.)
    """
    home = os.path.expanduser("~")
    room = None
    try:
        _, r = _req("POST", "/api/rooms", {"name": "_probe_listdir", "workspace_path": home})
        room = r["id"]
        # 큰 트리를 훑는 fs/list를 치면서 동시에 health가 빠른지
        t0 = time.monotonic()
        _req("GET", f"/api/fs/list?path={home}", timeout=10)
        _, _ = _req("GET", "/api/health", timeout=3)
        dt = time.monotonic() - t0
        if dt > 8:
            raise ProbeFail(f"홈 fs/list 중 응답이 느림({dt:.1f}s) — 폭주 방어 확인 필요")
        _ok(f"홈 디렉터리 조회 중에도 서버 응답 유지({dt:.2f}s)")
    finally:
        if room:
            _req("DELETE", f"/api/rooms/{room}", timeout=15)


def check_model_tier_per_session():
    """모델 티어가 세션별로 독립 유지된다(전역 하나만 보던 버그 회귀)."""
    a = b = None
    try:
        _, ra = _req("POST", "/api/rooms", {"name": "_probe_tier_a"})
        _, rb = _req("POST", "/api/rooms", {"name": "_probe_tier_b"})
        a, b = ra["id"], rb["id"]
        _req("POST", f"/api/sessions/{a}/model-tier", {"tier": "pro"})
        _req("POST", f"/api/sessions/{b}/model-tier", {"tier": "flash"})
        _, rooms = _req("GET", "/api/rooms")
        tiers = {r["id"]: r.get("model_tier") for r in rooms}
        if tiers.get(a) != "pro" or tiers.get(b) != "flash":
            raise ProbeFail(f"세션별 티어가 섞임: a={tiers.get(a)} b={tiers.get(b)}")
        # 잘못된 값 방어
        _, resp = _req("POST", f"/api/sessions/{a}/model-tier", {"tier": "해킹"})
        if resp.get("tier") != "auto":
            raise ProbeFail(f"잘못된 티어가 방어되지 않음: {resp}")
        _ok("모델 티어 세션별 독립 + 잘못된 값 방어")
    finally:
        for x in (a, b):
            if x:
                _req("DELETE", f"/api/rooms/{x}", timeout=15)


def check_image_inline():
    """첨부 이미지가 data URI로 변환돼 모델에 전달된다(경로 문자열 그대로 넘기던 버그)."""
    from app.api.routes import UPLOADS_DIR, _inline_upload
    png = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    name = "_probe_inline.png"
    (UPLOADS_DIR / name).write_bytes(png)
    try:
        out = _inline_upload(f"/uploads/{name}")
        if not out.startswith("data:image/png;base64,"):
            raise ProbeFail(f"업로드가 data URI로 변환 안 됨: {out[:40]}")
        _ok("첨부 이미지 → data URI 변환")
    finally:
        (UPLOADS_DIR / name).unlink(missing_ok=True)


# ─── LLM end-to-end (--full) ─────────────────────────────────────────

def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_full_task():
    """실제 세션 1회 — gate 생성·완료 보고 형식·프로젝트 메모리 provenance·자동 커밋."""
    tmp = tempfile.mkdtemp(prefix="forge-probe-")
    ws = os.path.join(tmp, "ws")
    origin = os.path.join(tmp, "origin.git")
    os.makedirs(ws)
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "probe@local")
    _git(ws, "config", "user.name", "probe")
    open(os.path.join(ws, "calc.py"), "w").write("def add(a, b):\n    return a + b\n")
    open(os.path.join(ws, "test_calc.py"), "w").write(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "init")
    _git(ws, "remote", "add", "origin", origin)
    _git(ws, "push", "-q", "-u", "origin", "HEAD")

    room = None
    try:
        _, r = _req("POST", "/api/rooms", {"name": "_probe_full", "workspace_path": ws, "mode": "work"})
        room = r["id"]
        print(f"  … 실제 세션 실행 중(비용 발생) room={room[:8]}")
        # SSE 스트림을 열어 done까지 읽는다
        body = json.dumps({"session_id": room, "message":
                           "calc.py에 sub(a,b) 뺄셈을 추가하고 test_calc.py에 테스트도 추가해라. "
                           "워크스페이스는 현재 디렉터리다.",
                           "auto_approve": True, "budget_usd": 0.4}).encode()
        req = urllib.request.Request(BASE + "/api/chat", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        done = None
        events = []
        with urllib.request.urlopen(req, timeout=300) as resp:
            for line in resp:
                s = line.decode(errors="replace").strip()
                if not s.startswith("data: "):
                    continue
                try:
                    e = json.loads(s[6:])
                except ValueError:
                    continue
                events.append(e.get("type"))
                if e.get("type") == "done":
                    done = e.get("data", {})
                    break
        if not done:
            raise ProbeFail("done 이벤트를 받지 못함")

        # 1) 완료 상태
        if done.get("status") not in ("completed", "completed_unverified"):
            raise ProbeFail(f"완료되지 않음: {done.get('status')}")
        _ok(f"작업 완료: {done.get('status')}")

        # 2) 완료 보고 형식 — 헤더 앞뒤 빈 줄
        content = done.get("content", "")
        head = content.split("\n")
        if not (head[0] == "" and head[1].startswith(("완료했습니다", "작업은 완료"))):
            raise ProbeFail(f"보고 헤더 형식 어긋남: {head[:3]}")
        _ok("완료 보고 형식(헤더 앞뒤 빈 줄)")

        # 3) gate 생성 여부
        _, gates = _req("GET", f"/api/sessions/{room}/gates")
        if not gates:
            raise ProbeFail("acceptance gate가 하나도 생성되지 않음")
        _ok(f"acceptance gate {len(gates)}개 생성·검증")

        # 4) 자동 커밋
        log = subprocess.run(["git", "-C", ws, "log", "--oneline"],
                             capture_output=True, text=True).stdout
        if "FORGE 자동 커밋" not in log:
            raise ProbeFail("자동 커밋이 안 됨")
        _ok("변경 자동 커밋")

        # 5) 프로젝트 메모리 provenance — 저장됐다면 source 근거가 붙어야 한다
        mem_path = os.path.join(ws, "ROOM_MEMORY.md")
        if os.path.isfile(mem_path):
            mem = open(mem_path, encoding="utf-8").read()
            facts = [l for l in mem.splitlines() if l.strip().startswith("- ")]
            if facts and "source:" not in mem:
                raise ProbeFail("프로젝트 메모리에 provenance(source:)가 없음")
            _ok(f"프로젝트 메모리 provenance({'적립됨' if facts else '적립 없음'})")
    finally:
        if room:
            _req("DELETE", f"/api/rooms/{room}", timeout=20)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="FORGE 자기 핵심 경로 프로브")
    ap.add_argument("--full", action="store_true", help="실제 LLM 작업 1회 포함(비용 발생)")
    args = ap.parse_args()

    checks = [
        ("서버 health", check_health),
        ("폭주 방어(응답성)", check_server_stays_responsive_under_listdir),
        ("모델 티어 세션별", check_model_tier_per_session),
        ("이미지 인라인", check_image_inline),
    ]
    if args.full:
        checks.append(("실제 작업 end-to-end", check_full_task))

    failed = []
    for name, fn in checks:
        print(f"[{name}]")
        try:
            fn()
        except ProbeFail as e:
            print(f"  ✗ {e}")
            failed.append(name)
        except Exception as e:
            print(f"  ✗ 예상치 못한 오류: {e}")
            failed.append(name)

    print()
    if failed:
        print(f"실패 {len(failed)}/{len(checks)}: {', '.join(failed)}")
        sys.exit(1)
    print(f"전 프로브 통과 ({len(checks)}/{len(checks)}) ✓")


if __name__ == "__main__":
    main()
