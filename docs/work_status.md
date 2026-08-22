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
- [x] Triage — 일반 대화와 코드 작업 분리
- [x] 역할 파이프라인 — Planner → Coder → Reviewer → Debugger
- [x] Model Router — 역할별 Pro / Flash / Vision 모델 정책
- [x] Vision Agent — 이미지 요청 사전 분석
- [x] 실행 중 사용자 메시지 injection
- [x] DeepSeek V4 raw HTTP thinking 명시 및 streaming usage 수집

## Phase 3 — Remote Operation (진행 중)

### 완료

- [x] 모바일 PWA 채팅 및 승인/질문 원격 제어
- [x] PWA foreground 시 서비스 워커 업데이트 확인
- [x] Git 변경 파일 / 파일별 diff / 커밋 히스토리 조회
- [x] Git 브랜치 조회 및 전환
- [x] 모바일 safe-area 대응

### 예정

- [ ] Reviewer → Debugger → Reviewer 자동 재검증 루프
- [ ] worker/executor 서비스 분리
- [ ] Redis Streams 기반 durable event log 및 재접속 복구
- [ ] Web Push
- [ ] Context Dashboard
- [ ] HANDOFF 생성 및 새 세션 인계

## Phase 4 — Advanced Extension (별도 프로젝트)

- Multi-Agent, MCP, Repository Intelligence, Vector Search, Vision Agent 고도화
