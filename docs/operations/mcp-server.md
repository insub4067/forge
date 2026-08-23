# FORGE MCP 서버 운영

FORGE를 외부 AI 에이전트(Claude·ChatGPT·IDE)가 호출하는 MCP 서버로 노출한다. 저수준 도구
(bash·write_file)는 노출하지 않고 high-level capability만 준다 — 자세한 설계는
[`../proposal/forge-mcp-agent-runtime.md`](../proposal/forge-mcp-agent-runtime.md).

## 노출 도구

| 도구 | 설명 |
|---|---|
| `forge_execute(goal, workspace, auto_approve)` | 목표 위임 → task_id 즉시 반환(비차단) |
| `forge_status(task_id)` | 진행 상태(running/role/승인·질문 대기) |
| `forge_result(task_id)` | 결과(최종 상태·요약·비용·토큰) |
| `forge_cancel(task_id)` | 중단 |

## 실행 (stdio)

```bash
cd backend && .venv/bin/python -m app.mcp.server
```

stdin/stdout으로 MCP 클라이언트와 JSON-RPC 2.0로 통신한다. 공식 SDK 없이 최소 구현이라
의존성이 없다. DB(PostgreSQL)와 DeepSeek API 키(.env)는 기존 backend와 동일하게 필요하다.

## Claude Desktop / MCP 클라이언트 등록 예

```json
{
  "mcpServers": {
    "forge": {
      "command": "/Users/insub/Desktop/forge/backend/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/Users/insub/Desktop/forge/backend"
    }
  }
}
```

## 비용·경계

- MCP는 transport다. FORGE 내부 토큰 사용은 위임이든 REST든 동일하다. **줄어드는 것은
  호출하는 상위 에이전트의 토큰** — 무거운 코딩 루프를 싼 DeepSeek 파이프라인에 떠넘긴다.
- approval/sandbox/workspace 경계는 facade가 호출하는 AgentRuntime이 그대로 적용한다.
  `auto_approve=true`는 무인 위임에서만 신중히 쓴다(쓰기·실행 자동 승인).

## 알려진 한계 (미구현)

- **durability 없음**: 서버 재시작 시 진행 중 task가 유실된다. 프로덕션 위임에는
  [`../proposal/durable-worker-resume.md`](../proposal/durable-worker-resume.md)의 D0/D1이 선결이다.
- **인증 없음**: 현재 stdio(로컬) 전제. remote(HTTP) 노출 시 토큰/정책 게이트가 필요하다.
- Resources(`forge://task/{id}/diff` 등)·capability 도구(forge_review 등)는 2차.
