# FORGE MCP 연결 가이드

외부 AI 에이전트(Claude Desktop·Claude Code·Cursor·기타 MCP 클라이언트)를 FORGE에 연결해
코딩 작업을 위임하는 방법. 설계·운영은 [`mcp-server.md`](mcp-server.md), 배경은
[`../proposal/forge-mcp-agent-runtime.md`](../proposal/forge-mcp-agent-runtime.md).

## 0. 선행 조건

- FORGE backend가 설치돼 있고 `.venv`가 준비됨(`backend/.venv`).
- PostgreSQL 실행 중, `.env`에 `DEEP_SEEK_API_KEY` 설정(기존 backend와 동일).
- MCP 서버는 별도 uvicorn 없이 단독 실행된다 — DB·API 키만 있으면 된다.

## 1. 연결 방식

FORGE MCP는 **stdio JSON-RPC 2.0** 서버다. 클라이언트가 프로세스를 띄우고 stdin/stdout으로
통신한다. 실행은 래퍼 스크립트 하나로 끝난다(cwd 자동 처리):

```
/Users/insub/Desktop/forge/backend/run_mcp.sh
```

## 2. 클라이언트별 등록

### Claude Desktop

`claude_desktop_config.json`(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`)에:

```json
{
  "mcpServers": {
    "forge": {
      "command": "/Users/insub/Desktop/forge/backend/run_mcp.sh"
    }
  }
}
```

저장 후 Claude Desktop 재시작. 도구 목록에 `forge_execute` 등이 뜨면 성공.

### Claude Code (CLI)

```bash
claude mcp add forge -- /Users/insub/Desktop/forge/backend/run_mcp.sh
```

`claude mcp list`로 확인, `/mcp`로 상태 조회.

### Cursor / 기타 MCP 클라이언트

대부분 `command` + `args`(옵션) 형식이다. command에 위 래퍼 경로를 지정한다.
직접 파이썬을 지정하려면:

```json
{ "command": "/Users/insub/Desktop/forge/backend/.venv/bin/python",
  "args": ["-m", "app.mcp.server"],
  "cwd": "/Users/insub/Desktop/forge/backend" }
```

(래퍼를 쓰면 `cwd` 지정이 필요 없다.)

## 3. 연결 검증 (클라이언트 없이 수동)

터미널에서 직접 JSON-RPC를 흘려 확인한다:

```bash
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | /Users/insub/Desktop/forge/backend/run_mcp.sh
```

`serverInfo.name == "forge"`와 도구 4개가 나오면 정상.

## 4. 사용 흐름 (에이전트 관점)

```
forge_execute(goal="로그인 버그를 찾아 수정하고 테스트까지", workspace="/projects/app")
   → { "task_id": "...", "status": "running" }        # 즉시 반환(비차단)
forge_status(task_id)
   → { "running": true, "role": "coder", ... }         # 진행 폴링
forge_result(task_id)                                    # 완료 후
   → { "final_status": "completed", "summary": "...", "cost": 0.001, "total_tokens": 13030 }
forge_cancel(task_id)                                    # 필요 시 중단
```

`goal`과 `workspace`는 필수. `auto_approve`(기본 false)를 true로 주면 쓰기·실행 도구를
자동 승인한다 — 무인 위임에서만 신중히 사용.

## 5. 보안 주의

- 현재 **stdio(로컬) 전제**. 같은 사용자 계정에서 실행되며 별도 인증이 없다.
- FORGE는 파일 쓰기·shell·git·host build 능력을 가진다. approval/sandbox/workspace 경계는
  facade가 호출하는 AgentRuntime이 그대로 적용하지만, `auto_approve=true` + host 모드 조합은
  강력하므로 신뢰하는 워크스페이스에만 위임한다.
- **remote(HTTP) 노출은 아직 미구현**이다. 외부 네트워크에 열려면 토큰/정책 게이트가 선결
  (`FORGE_AUTH_TOKEN` 유사 계층 + [`../proposal/forge-mcp-agent-runtime.md`](../proposal/forge-mcp-agent-runtime.md) §13).

## 6. 트러블슈팅

| 증상 | 원인·조치 |
|---|---|
| 도구 목록이 안 뜸 | 래퍼 경로·실행권한(`chmod +x run_mcp.sh`) 확인, `.venv` 존재 확인 |
| `forge_execute` 후 결과 없음 | DB 연결·`DEEP_SEEK_API_KEY` 확인. `forge_status`로 role 진행 확인 |
| task가 재시작 후 사라짐 | durability 미구현(알려진 한계) — `../proposal/durable-worker-resume.md` 참고 |
| 저수준 도구(bash 등)가 안 보임 | 의도된 설계 — high-level 도구만 노출(§12) |
