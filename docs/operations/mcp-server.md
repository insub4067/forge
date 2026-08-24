# FORGE MCP Server

FORGE를 Claude/ChatGPT/IDE 등 외부 orchestration agent가 호출할 수 있는 **local stdio MCP task facade**로 노출한다. 저수준 bash/write 도구는 직접 노출하지 않는다.

## 현재 도구

| Tool | 설명 |
|---|---|
| `forge_execute(goal, workspace, plan?, images?, auto_approve?)` | 새 session/task 시작, `task_id` 즉시 반환 |
| `forge_status(task_id)` | running/role/approval/question 등 live 상태 |
| `forge_result(task_id)` | final_status, process-owned 마지막 assistant summary, 비용/토큰 |
| `forge_cancel(task_id)` | 실행 중 task cancel |

`task_id == session_id`다.

## 실행

```bash
cd backend
.venv/bin/python -m app.mcp.server
```

stdio JSON-RPC 2.0, MCP protocol version `2025-06-18`. 공식 SDK 의존 없이 최소 구현이다.

## Plan / Image delegation

상위 agent가 `plan`을 주면 이를 user content에 포함해 FORGE가 그 계획을 실행하도록 할 수 있다. 이미지 파일 절대경로를 `images`로 주면 data URI로 변환해 기존 vision route를 재사용한다.

## Durability truth

MCP process 자체는 durable worker가 아니다. `asyncio.create_task`로 current process에서 run을 시작한다.

하지만 task identity/history는 PostgreSQL session에 저장되고 global FORGE Auto Resume가 켜져 있으면 서버 재시작으로 interrupted된 동일 session을 history 기반으로 재개할 수 있다. 따라서 과거 문서의 “재시작 시 task_id가 완전히 유실된다”는 설명은 더 이상 정확하지 않다.

정확한 한계:

- stdio 연결 자체는 프로세스 재시작 시 다시 연결해야 한다.
- resume는 coroutine checkpoint continuation이 아니라 persisted history/state에서 새 run을 재구성한다.
- independent worker queue/process ownership은 아직 없다.

## Security

- 현재 transport는 local stdio라 별도 remote auth를 제공하지 않는다.
- `auto_approve=true`는 기존 AgentRuntime approval을 자동 승인하므로 신뢰 환경에서만 사용한다.
- workspace/sandbox/dangerous-command/verification 경계는 AgentRuntime을 재사용한다.
- remote HTTP MCP는 현재 구현이 아니며 구현 시 별도 auth/policy가 필요하다.

## 미구현

- remote MCP transport
- MCP Resources (`forge://...`)
- 추가 review/diff capability tools
- independent durable worker queue
