"""MCP stdio 서버 프로토콜 검증 — facade를 목킹해 LLM 비용 없이 JSON-RPC 흐름만 확인."""
import asyncio, json
from unittest import mock
from app.mcp import server


async def main():
    # 1) initialize → protocolVersion·capabilities·serverInfo
    r = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["result"]["protocolVersion"] == server.PROTOCOL_VERSION, r
    assert "tools" in r["result"]["capabilities"], r
    assert r["result"]["serverInfo"]["name"] == "forge", r

    # 2) initialized notification → 응답 없음
    assert await server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    # 3) tools/list → 4개 high-level 도구, 저수준 도구 미노출
    r = await server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["forge_execute", "forge_status", "forge_result", "forge_cancel"], names
    for banned in ("bash", "write_file", "edit_file", "build_frontend"):
        assert banned not in names, f"저수준 도구 노출됨: {banned}"

    # 4) tools/call forge_execute (facade 목킹 — LLM 실행 안 함)
    async def fake_execute(goal, workspace, auto_approve=False, plan=""):
        assert goal and workspace
        return "task_abc"
    with mock.patch.object(server.task_facade, "execute", fake_execute):
        r = await server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "forge_execute",
                                            "arguments": {"goal": "버그 고쳐", "workspace": "/tmp/x"}}})
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["task_id"] == "task_abc" and payload["status"] == "running", r
    assert r["result"]["isError"] is False

    # 5) 필수 인자 누락 → isError
    r = await server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "forge_execute", "arguments": {"goal": "x"}}})
    assert r["result"]["isError"] is True, r

    # 6) forge_status / result / cancel (facade 목킹)
    with mock.patch.object(server.task_facade, "status", lambda tid: {"running": True, "role": "coder"}):
        r = await server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                 "params": {"name": "forge_status", "arguments": {"task_id": "t"}}})
        assert json.loads(r["result"]["content"][0]["text"])["role"] == "coder"
    with mock.patch.object(server.task_facade, "cancel", lambda tid: True):
        r = await server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                                 "params": {"name": "forge_cancel", "arguments": {"task_id": "t"}}})
        assert json.loads(r["result"]["content"][0]["text"])["cancelled"] is True

    # 7) 미지원 method → JSON-RPC error
    r = await server.handle({"jsonrpc": "2.0", "id": 7, "method": "foo/bar"})
    assert r["error"]["code"] == -32601, r

    print("MCP 서버 프로토콜 테스트 통과 ✓ (initialize/list/call·저수준 미노출·에러·notification)")

asyncio.run(main())
