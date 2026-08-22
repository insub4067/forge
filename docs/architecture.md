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
Planner (계획 생성)
    ↓
Tool 실행
    ↓
Observation (결과 관찰)
    ↓
재계획 (필요 시 반복)
    ↓
완료 판단 → Report
```

필수 기능: Planning, Tool Loop, Retry, Step Limit, State 저장, Interrupt.

## LLM Adapter 구조

```
Agent Runtime → LLM Adapter Interface → DeepSeek V4 Pro Provider
```

- DeepSeek 최적화: Streaming, Thinking Mode, Effort Control, Prefix Cache
- Prefix Cache 고정 순서: System Prompt → Agent Policy → Tool Schema → Project Rules
- 금지: Timestamp, Random ID, Dynamic Prompt

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
