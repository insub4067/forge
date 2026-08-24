# FORGE MCP 연결 가이드

외부 MCP 클라이언트가 FORGE에 코딩 작업을 위임하는 방법. 운영 의미는 [`mcp-server.md`](mcp-server.md)를 먼저 본다.

## 선행 조건

- `backend/.venv` 준비
- PostgreSQL 실행
- `.env`에 DeepSeek API key 설정

MCP 서버는 uvicorn 없이 독립 stdio process로 실행되지만 DB와 같은 Runtime 설정을 사용한다.

## 실행/등록

직접:

```bash
cd /path/to/forge/backend
.venv/bin/python -m app.mcp.server
```

`run_mcp.sh`를 쓰는 설치라면 client의 command를 그 스크립트로 지정한다.

Claude Desktop 예:

```json
{
  "mcpServers": {
    "forge": {
      "command": "/path/to/forge/backend/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/path/to/forge/backend"
    }
  }
}
```

Claude Code 예:

```bash
claude mcp add forge -- /path/to/forge/backend/run_mcp.sh
```

## 수동 연결 확인

```bash
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | /path/to/forge/backend/run_mcp.sh
```

`serverInfo.name == "forge"`와 도구 4개가 보이면 transport는 정상이다.

## 사용

```text
forge_execute(goal, workspace, plan?, images?, auto_approve?)
→ task_id

forge_status(task_id)
→ running / current role / waiting state

forge_result(task_id)
→ final_status / summary / cost / tokens

forge_cancel(task_id)
```

`plan`은 상위 agent가 계획을 제공할 때 사용한다. `images`는 로컬 이미지 절대경로 배열이다.

## 재시작

- `task_id`는 session id라 DB history/result와 연결된다.
- FORGE `AUTO_RESUME=1`이면 서버 재시작으로 interrupted된 유효 workspace task를 동일 session에서 history 기반으로 재개한다.
- MCP stdio client connection은 재연결해야 한다.
- `final_status == resuming`에서 다시 죽은 run은 crash-loop 방지를 위해 자동 재재개하지 않는다.

## 보안

- stdio/local 전제, remote MCP는 미구현.
- `auto_approve=true` + host mode는 높은 권한 조합이다.
- 저수준 bash/write가 MCP tools에 안 보이는 것은 의도된 narrow capability surface다.

## Troubleshooting

| 증상 | 확인 |
|---|---|
| tools가 안 뜸 | command/cwd/.venv, `tools/list` 수동 호출 |
| execute 후 진행 안 됨 | DB/API key, `forge_status`, backend error log |
| 재시작 후 running=false | Auto Resume 조건(workspace 유효, crash-loop state 아님) 확인 |
| result는 있는데 stdio가 끊김 | transport만 재연결 후 같은 task_id로 `forge_result` |
| bash/write tool이 없음 | 정상 — high-level 4 tools만 노출 |
