# FORGE — 요구사항 정의서

**문서 버전** v0.3
**코드네임** `FORGE`
**목표** 개인 개발 환경에서 사용하는 셀프호스팅 Agent Runtime 기반 코딩 AI 플랫폼

---

## 1. 프로젝트 개요

FORGE는 특정 LLM에 종속된 챗봇이 아니라, LLM을 두뇌로 활용하는 **Agent Runtime 플랫폼**이다.

```
요구사항 분석 → 작업 계획 생성 → Repository 탐색 → 코드 수정 → 실행 및 검증 → 결과 보고
```

## 2. 핵심 설계 원칙

LLM은 판단 엔진이며 Agent가 아니다.

| 주체 | 역할 |
|---|---|
| LLM | 계획 생성, 코드 분석, 코드 작성, 문제 해결 |
| Agent Runtime | 작업 상태 관리, Tool 실행, 권한 제어, 실패 복구, Context 관리, 장기 실행 관리 |

```
User → Agent Runtime → LLM Provider → Tool Executor → Execution Environment
```

## 3. v1 목표 범위

**포함**: Agent Loop, DeepSeek V4 Pro 연동, Tool Calling, Docker Sandbox, 승인 게이트, SSE Streaming, Context Management, Session 관리, Checkpoint, HANDOFF 생성, Mobile PWA 원격 제어

**제외(v2 이후)**: Multi-Agent, MCP, Repository AST Intelligence, Vector Search, Browser Agent, Vision Agent, 자체 모델 운영

## 4. 서비스 구성

| 서비스 | 역할 |
|---|---|
| web | Vue3 PWA |
| api | 인증/API Gateway |
| worker | Agent 실행 엔진 |
| executor | Docker 기반 코드 실행 환경 |
| redis | 작업 큐 및 이벤트 스트림 |
| postgres | 세션 및 감사 데이터 |

## 5. Tool System

| Tool | 설명 |
|---|---|
| read_file | 파일 읽기 |
| list_dir | 디렉터리 탐색 |
| grep | 코드 검색 |
| edit_file | 부분 수정 |
| write_file | 파일 생성 |
| bash | 명령 실행 |
| git | Git 관리 |
| test | 테스트 실행 |

## 6. Tool 권한 정책

| 정책 | Tool |
|---|---|
| 자동 실행 | read_file, list_dir, grep, git status, git diff |
| 승인 필요 | edit_file, write_file, bash, git commit, dependency 변경 |
| 차단 | rm -rf, credential 접근, secret 출력, git push |

## 7. Sandbox 실행 정책

- Non-root, Capability 제거, Resource 제한
- Workspace만 write 가능, Docker socket 접근 금지
- 네트워크는 Proxy 기반 Whitelist (github.com, npm registry, pypi.org)

## 8. Streaming 이벤트

```
thinking_delta, text_delta, tool_call, tool_result,
plan_update, approval_request, context_usage, error, done
```

모든 이벤트는 `{"seq":1284,"type":"tool_call","data":{}}` 형태. Redis Streams에 저장해 재접속/모바일 복구/다중 클라이언트를 지원.

## 9. Context Management

- 측정: 요청 전(로컬 tokenizer 추정) / 스트리밍 중(delta 누적) / 완료 후(API usage 보정)
- Logical Budget 기본 256K tokens
- 임계 정책: Normal(0~59%) / Notice(60~74%) / Warning(75~84%) / Critical(85~94%) / Blocked(95%+)

## 10. Context Compaction

압축 시 보존: 사용자 요구사항, 설계 결정, 변경 파일, 실패한 접근, 남은 TODO.
삭제 우선: 긴 Tool 출력, 반복 로그. 결과로 `HANDOFF.md` 생성.

## 11. Session Handoff

`HANDOFF.md` 형식: 원 요구사항, 완료 작업, 현재 상태, 결정 사항, 실패 기록, 다음 작업, 관련 파일.

## 12. Project Memory

- Session Memory: 현재 작업·대화 범위
- Project Memory: 프로젝트 규칙, 반복 실패, 기술 결정 (`PROJECT_MEMORY.md`)

## 13. 데이터 모델

- **sessions**: id, title, workspace_id, status, model, logical_budget, created_at, archived_at
- **messages**: id, session_id, seq, role, content_json, prompt_tokens, completion_tokens, cached_tokens, cost
- **tool_calls**: id, message_id, tool_name, args_json, result, status, risk_level, duration_ms
- **approvals**: id, tool_call_id, decision, scope, requested_at, decided_at
- **checkpoints**: id, session_id, git_sha, step_no, created_at
- **audit_logs**: id, actor, action, payload, created_at

## 14. Non Functional Requirements

- **성능**: First Token 3초 이내, Streaming latency 200ms 이하
- **보안**: API Key 서버 보관, Secret Manager, 모든 Tool Audit 기록
- **안정성**: API 재시작 시 Worker 유지, 세션 데이터 영속화
- **배포**: `docker compose up`으로 실행

## 15. 개발 단계

| Phase | 목표 | 구현 |
|---|---|---|
| 1 | Agent Core | FastAPI, Vue, DeepSeek, Agent Loop, Docker Sandbox, Read Tool |
| 2 | Code Modification | edit_file, write_file, bash, Approval, Diff View |
| 3 | Remote Operation | Mobile PWA, Web Push, Context Dashboard, HANDOFF |
| 4 | Advanced Extension | Multi-Agent, MCP, Repository Intelligence, Vector Search, Vision Agent |

## 16. Open Questions

1. 단독 사용인가 팀 공유인가? → **단독 사용**
2. Workspace는 local mount인가 git clone인가? → **local mount**
3. 외부 공개인가 VPN 환경인가?
4. 월 API 비용 제한은?
5. 모바일에서 코드 수정까지 필요한가?
6. 기본 Logical Budget 256K가 적절한가?
