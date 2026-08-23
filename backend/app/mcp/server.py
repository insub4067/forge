"""FORGE MCP stdio 서버 — 외부 에이전트(Claude·ChatGPT·IDE)가 FORGE에 코딩 작업을 위임.

MCP proposal 구현. 저수준 도구(bash·write_file)는 노출하지 않고 high-level capability만:
  forge_execute(goal, workspace, auto_approve) → task_id
  forge_status(task_id)  → 진행 상태
  forge_result(task_id)  → 결과(요약·비용·토큰)
  forge_cancel(task_id)  → 중단

전송은 stdio JSON-RPC 2.0(줄바꿈 구분). 공식 SDK 없이 최소 구현 — 의존성 0.
approval/sandbox/workspace 경계는 facade가 호출하는 AgentRuntime이 그대로 적용(§11).

실행: python -m app.mcp.server   (stdin/stdout으로 MCP 클라이언트와 통신)
"""
import asyncio
import json
import sys

from ..runtime import task_facade

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "forge", "version": "0.1.0"}

TOOLS = [
    {
        "name": "forge_execute",
        "description": "FORGE 코딩 에이전트에 작업을 위임한다. plan을 주면 FORGE는 내부 계획을 건너뛰고 코딩(Coder→Reviewer→Debugger)만 한다 — 추론·계획은 호출하는 당신(상위 모델)이 하고, FORGE는 값싼 실행만 담당. plan을 안 주면 FORGE가 계획까지 전부 처리한다. 비차단 — task_id를 즉시 반환하고 forge_status로 진행을 조회한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "달성할 목표(자연어). 예: '로그인 버그를 찾아 수정하고 테스트까지 완료'"},
                "workspace": {"type": "string", "description": "작업할 로컬 워크스페이스 절대경로"},
                "plan": {"type": "string", "description": "선택. 당신이 세운 단계별 실행 계획. 주면 FORGE 내부 planner를 건너뛰고 이 계획대로 코딩만 한다(비용↓). 복잡한 작업일수록 구체적 계획을 넘기는 것을 권장."},
                "auto_approve": {"type": "boolean", "description": "쓰기/실행 도구를 자동 승인할지(무인 위임 시 true). 기본 false", "default": False},
            },
            "required": ["goal", "workspace"],
        },
    },
    {
        "name": "forge_status",
        "description": "위임한 task의 현재 상태(실행 중 여부·현재 role·승인/질문 대기)를 조회한다.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
    },
    {
        "name": "forge_result",
        "description": "완료된 task의 결과(최종 상태·요약·비용·토큰 사용량)를 가져온다.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
    },
    {
        "name": "forge_cancel",
        "description": "실행 중인 task를 중단한다.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
    },
]


async def _call_tool(name: str, args: dict) -> dict:
    """도구 실행 → MCP content 블록. 위임·정책·sandbox는 facade→AgentRuntime이 담당."""
    if name == "forge_execute":
        goal = str(args.get("goal", "")).strip()
        workspace = str(args.get("workspace", "")).strip()
        if not goal or not workspace:
            return _text("goal과 workspace는 필수입니다.", is_error=True)
        task_id = await task_facade.execute(goal, workspace, bool(args.get("auto_approve", False)),
                                            plan=str(args.get("plan", "")))
        return _text(json.dumps({"task_id": task_id, "status": "running"}, ensure_ascii=False))
    if name == "forge_status":
        return _text(json.dumps(task_facade.status(str(args.get("task_id", ""))), ensure_ascii=False))
    if name == "forge_result":
        return _text(json.dumps(await task_facade.result(str(args.get("task_id", ""))), ensure_ascii=False))
    if name == "forge_cancel":
        ok = task_facade.cancel(str(args.get("task_id", "")))
        return _text(json.dumps({"cancelled": ok}, ensure_ascii=False))
    return _text(f"알 수 없는 도구: {name}", is_error=True)


def _text(s: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": s}], "isError": is_error}


async def handle(msg: dict) -> dict | None:
    """JSON-RPC 요청 하나를 처리. notification(id 없음)은 None 반환(응답 안 함)."""
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return _ok(mid, {"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
    if method in ("notifications/initialized", "initialized"):
        return None  # notification — 응답 없음
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            res = await _call_tool(params.get("name", ""), params.get("arguments") or {})
            return _ok(mid, res)
        except Exception as err:
            return _err(mid, -32603, f"tool 실행 오류: {err}")
    if mid is None:
        return None  # 알 수 없는 notification 무시
    return _err(mid, -32601, f"미지원 method: {method}")


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


async def main():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = await handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
