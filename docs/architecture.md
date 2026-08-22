# FORGE — 시스템 아키텍처

## 전체 구조

```
┌───────────────┐
│ Vue3 PWA      │  Desktop / Mobile
│ (web)         │
└───────┬───────┘
        │ SSE + REST
┌───────▼────────┐
│ FastAPI Gateway│  (api)
│ - 인증/라우팅   │
└───────┬────────┘
        │
┌───────▼──────────┐
│ Agent Worker     │  (worker)
│ Runtime Engine   │  Planner → Tool Loop → Observation
└───┬─────────┬────┘
    │         │
┌───▼───┐ ┌───▼────────┐
│DeepSeek│ │ Tool Runner│  (executor)
│Adapter │ │ Sandbox    │  Docker Container
└────────┘ └────┬───────┘
                │
┌───────▼────────┐
│ PostgreSQL     │  세션·감사 데이터
│ Redis Streams  │  작업 큐·이벤트 스트림
└────────────────┘
```

## 서비스 구성

| 서비스 | 역할 | 상태 |
|---|---|---|
| web | Vue3 PWA (Desktop/Mobile) | ✅ Phase 1 기본 UI |
| api | FastAPI Gateway + SSE | ✅ |
| worker | Agent 실행 엔진 | ✅ (api와 동일 프로세스, Phase 3에서 분리) |
| executor | Docker 기반 코드 실행 환경 | ⬜ executor 클래스 구현, bash 연결은 Phase 2 |
| redis | 작업 큐·이벤트 스트림 | ⬜ docker-compose만 구성, Phase 3 연결 |
| postgres | 세션·감사 데이터 | ⬜ 모델/스키마 구현, 영속화 연결 예정 |

## Agent Runtime 실행 흐름

```
User Request
    ↓
Triage ──(chat)──→ 단일 Chat 패스
    │ (agent)
    ↓
Planner → Coder → [ Reviewer ↔ Debugger 자기수정 루프 ] → Report
```

- Triage가 일반 대화(chat)와 코드 작업(agent)을 분리한다.
- Reviewer가 DB task 상태(`done`/`debug`)로 성공/결함을 판정하고, 결함이 있으면
  Debugger가 수정 후 `review`로 되돌려 Reviewer가 재검증한다. 모든 task가 `done`이 될
  때까지 최대 `MAX_REVIEW_CYCLES`(3)회 반복하고, 초과하면 남은 문제를 보고한다.
- Debugger는 마지막 복구 시도에서만 Pro로 승격(`retry_count >= 3`)해 비용을 억제한다.

자세한 흐름·종료 상태: [`agent-loop.md`](agent-loop.md).

필수 기능: Planning, Tool Loop, Self-Correction, Retry, Step/Cycle Limit, State 저장, Interrupt.

## LLM Adapter 구조

```
Agent Runtime → Model Router → LLM Adapter Interface → Provider (DeepSeek 등)
```

- DeepSeek 최적화: Streaming, Thinking Mode, Effort Control, Prefix Cache
- Prefix Cache 고정 순서: System Prompt → Agent Policy → Tool Schema → Project Rules
- 금지: Timestamp, Random ID, Dynamic Prompt

## Model Router

`orchestrator/model_router.py` — 역할별 모델·thinking·effort를 선택한다.

| Agent | 모델 | Thinking | Effort |
|---|---|---|---|
| Planner | deepseek-v4-pro | on | high |
| Coder | deepseek-v4-flash | off | low |
| Reviewer | deepseek-v4-flash | on | medium |
| Debugger | deepseek-v4-flash → pro | off → on | low → high |

- Debugger escalation: `retry_count >= 3` 또는 `complexity == "high"`
- 정책은 관리자 API(`/api/admin/model-policy`)로 런타임 조회·변경
- 실행 이력은 `agent_runs`에 model·thinking·effort 포함 기록

## Sandbox 실행

```
Agent → Executor → Docker Container → Workspace
```

정책: Non-root, Capability 제거, Resource 제한(memory/cpu/pids), Workspace만 write, Docker socket 금지.

네트워크: `Executor → Network Proxy → Whitelist` (github.com, npm registry, pypi.org)

## Streaming 아키텍처

- SSE Streaming + REST Control API
- 이벤트: `thinking_delta, text_delta, tool_call, tool_result, plan_update, approval_request, context_usage, error, done`
- Redis Streams 저장 목적: 재접속, 모바일 복구, 다중 클라이언트

## 코드 구조

```
forge/
├── backend/
│   └── app/
│       ├── main.py          # FastAPI 앱, 정적 서빙
│       ├── config.py        # pydantic-settings 설정
│       ├── api/routes.py    # SSE + REST 엔드포인트
│       ├── runtime/agent.py # Agent Runtime (Planner→Loop→Report)
│       ├── llm/deepseek.py  # DeepSeek Adapter (streaming)
│       ├── tools/registry.py# 도구 스키마 + 실행
│       ├── sandbox/executor.py # Docker Sandbox
│       └── db/              # SQLAlchemy 모델/세션
├── frontend/                # Vue3 + Vite PWA
├── sandbox/Dockerfile       # 격리 실행 이미지
└── docker-compose.yml       # postgres + redis
```
