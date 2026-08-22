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
- [x] Reviewer → Debugger → Reviewer 상태 기반 자기수정 루프 (최대 3회, 초과 시 남은 문제 보고)
- [x] Debugger 마지막 시도 Pro 승격 (retry_count 실제 연결)
- [x] 종료 상태 구분 — done 이벤트 status (completed/review_limit/cancelled/context_blocked/max_steps/repeated_tool_call/failed)

## Phase 3 — Remote Operation (진행 중)

### 완료 — 원격 제어 · 모바일 UI

- [x] 모바일 PWA 채팅 및 승인/질문 원격 제어
- [x] PWA foreground 시 서비스 워커 업데이트 확인
- [x] Git 추적 화면 — GitHub Desktop 스타일(변경/히스토리/브랜치 탭, 파일별 diff, 커밋 상세)
- [x] 모바일 safe-area 대응(헤더·푸터·드로어·오버레이 전역)
- [x] 모바일 UI 개편 — 헤더 축소·좌측 세션 드로어(스와이프 오픈)·Quick Action·Composer 통합
- [x] 컨텍스트 링 탭 → 세션 사용량 상세(컨텍스트 윈도우·누적 토큰·에이전트별)
- [x] 관리자 — 에러 로그 진입점, 에이전트별 토큰 소비 카드
- [x] 앱 실행 시 가장 최근 세션 랜딩
- [x] 파일 브라우저 숨김 파일 토글

### 완료 — Agent Loop 안정성/효율 (핵심)

- [x] Triage — 일반 대화(chat, 읽기 전용 fast path)와 코드 작업(agent) 분리
- [x] Reviewer → Debugger → Reviewer 상태 기반 자기수정 루프 (최대 3회, 초과 시 남은 문제 보고)
- [x] Debugger 마지막 시도 Pro 승격 (retry_count 실제 연결)
- [x] 종료 상태 구분 — done 이벤트 status
- [x] LLM 스텝 오류 자가 회복 — reasoning_content 400에 죽지 않고 reasoning 벗겨 재시도(세션별 학습)
- [x] 실행 중 사용자 메시지 개입 — 작업 대기(inject) / 계획 수정(중단 후 재시작)
- [x] 도구 자동 승인 모드 — 세션별 플래그, 실행 중 토글
- [x] 대화 지속성 — 사용자 메시지를 수신 즉시 저장(크래시·앱 종료에도 유실 방지)
- [x] Agent Activity — role별 phase 활동 카드(텍스트 항상 표시, 도구 로그 접힘)
- [x] 응답 생성 중 스크롤 위치 유지 + 맨아래 이동 화살표
- [x] DeepSeek V4 raw HTTP thinking 명시 및 streaming usage 수집

### 예정 (우선순위순)

- [ ] **planner 탐색 예산 제한** — 측정상 planner가 전체 토큰의 67%(~103k/회)를 소비. 저비용 반복 철학 위반, 최우선 개선 대상
- [ ] **Context Compaction** — tool result pruning + summary compaction (95% 중단 대신 압축 후 계속). `docs/proposal/deepseek-harness-adoption.md` §3
- [ ] Provider Error Recovery 일반화 — 429/500/timeout backoff·재시도(현재 reasoning_content만 회복)
- [ ] Durable Event Log + 세션 재개 — 서버 재시작·재접속 후 실행 상태 복구(Redis Streams). harness §4 / Phase B
- [ ] worker/executor 서비스 분리
- [ ] Web Push, HANDOFF

> 상세 로드맵: [`proposal/deepseek-harness-adoption.md`](proposal/deepseek-harness-adoption.md)

## Phase 4 — Advanced Extension (별도 프로젝트)

- Multi-Agent, MCP, Repository Intelligence, Vector Search, Vision Agent 고도화
