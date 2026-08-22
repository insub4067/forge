# FORGE — 작업 진행 상태

> 마지막 갱신: 2026-08-22

## Phase 1 — Agent Core (완료)

안전하게 코드를 읽고 분석하는 Agent.

### 완료

- [x] 프로젝트 스캐폴딩 (`forge/`, docker-compose, backend/frontend 구조)
- [x] DeepSeek Adapter — streaming + tool calling + thinking mode (`backend/app/llm/deepseek.py`)
- [x] Agent Runtime — Planner → Tool Loop → Observation → Report (`backend/app/runtime/agent.py`)
- [x] Read 도구 — read_file / list_dir / grep (`backend/app/tools/registry.py`)
- [x] FastAPI API + SSE 스트리밍 (`backend/app/api/routes.py`)
- [x] Docker Sandbox executor + 이미지 빌드 (`forge-sandbox:latest`)
- [x] DB 모델 + 세션·메시지 영속화 (`backend/app/db/store.py`)
- [x] Vue3 PWA 기본 UI (`frontend/`) — 채팅, 추론/도구 표시, 세션
- [x] 정적 서빙·API 라우팅 분리 (`/assets` mount + SPA fallback)
- [x] postgres + redis 컨테이너 실행 (docker-compose)
- [x] 문서화 — spec / architecture / feat / README

## Phase 2 — Code Modification (완료)

- [x] write_file / edit_file / bash 도구
- [x] bash — Docker Sandbox 격리 실행 (non-root, 리소스 제한)
- [x] 승인 게이트 — approval_request / approval_granted 이벤트 + `/api/approvals`
- [x] 사용자 질문 — ask_user 도구 + question_request + `/api/questions`
- [x] 보호 장치 — 동일 도구 3회 반복 감지, 컨텍스트 한도(95%) 중단
- [x] 사용자 중단 — `/api/sessions/{id}/cancel`
- [x] State 추적 — goal / files_changed / errors (state_update 이벤트)
- [x] Checkpoint — 변경 도구 실행 전 git sha 기록
- [x] Diff View — write_file/edit_file 변경 전후 unified diff 표시

## Phase 3 — Remote Operation (예정)

- worker/executor 서비스 분리
- Redis Streams (재접속·모바일 복구)
- Web Push, Context Dashboard, HANDOFF

## Phase 4 — Advanced Extension (별도 프로젝트)

- Multi-Agent, MCP, Repository Intelligence, Vector Search, Vision Agent
