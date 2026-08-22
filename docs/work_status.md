# FORGE — 작업 진행 상태

> 마지막 갱신: 2026-08-22 19:41 KST 기준 `main`

## 현재 요약

- Phase 1 — Agent Core: 완료
- Phase 2 — Code Modification: 완료
- Phase 3 — Remote Operation: 진행 중
- 최적화 기준: **cost per successfully completed task**

## 완료 — Agent Runtime

- [x] DeepSeek V4 streaming/tool calling/thinking
- [x] Triage: CHAT / AGENT + SIMPLE / COMPLEX 분류
- [x] Planner: Flash + medium 기본, COMPLEX만 Pro + high
- [x] Coder: Flash/non-thinking
- [x] Reviewer ↔ Debugger task 상태 기반 자기수정 루프
- [x] Debugger 마지막 복구 시도 Pro 승격
- [x] 종료 상태 구분(completed/review_limit/cancelled/context_blocked/max_steps/repeated_tool_call/failed)
- [x] 동일 tool+args 3회 반복 차단
- [x] 동일 세션 동시 run 가드
- [x] 실행 중 메시지 injection
- [x] cancel

## 완료 — Tool / 안전

- [x] read_file / list_dir / grep
- [x] write_file / edit_file / bash
- [x] ask_user / update_tasks / save_skill
- [x] write/edit/bash/save_skill 승인 게이트
- [x] 승인/질문 최대 600초 timeout
- [x] cancel 시 pending approval/question future 해제
- [x] mutation 전 git SHA checkpoint
- [x] write/edit unified diff
- [x] Docker Sandbox(non-root/resource limit) 기본 모드
- [x] `SANDBOX_MODE=host` 옵트인 host 실행(`/workspace` → 실제 workspace 치환)
- [x] 파일 브라우저 `/fs/list`, `/fs/read` workspace 경계 제한

> Host mode는 격리를 우회하므로 신뢰된 개인 환경에서만 사용한다.

## 완료 — 비용/Context 효율

- [x] provider 실측 `prompt_tokens` 기반 context pressure
- [x] 75% 비파괴 context compaction
- [x] compaction 성공 직후 압축 전 usage로 오차단하지 않고 다음 call 재측정
- [x] 95% hard block
- [x] 긴 tool result model-free pruning
- [x] read-only 다중 tool 병렬 prefetch
- [x] Stable Prefix(BASE + role) 고정 및 prefix hash
- [x] DeepSeek cache hit/miss/ratio 분리 계측
- [x] Skill selective retrieval(상위 최대 3개, 총 6000자 budget)
- [x] Planner Pro 기본 사용 제거
- [x] 429/5xx/timeout/connection 1/2/4초 retry
- [x] reasoning_content 오류 → thinking off recovery

## 완료 — Skills / Memory

- [x] `save_skill` 승인 기반 Skill 저장
- [x] `.forge/skills/*.md` 재사용
- [x] 관련 Skill만 선택 로딩
- [x] Skills UI 확인/삭제
- [x] Skills 카드 collapsible / 기본 닫힘
- [x] Session search
- [x] FORGE 자체 개발 workflow/convention/runtime Skill 저장

## 완료 — Persistence / Telemetry

- [x] PostgreSQL session/message/task/checkpoint 영속화
- [x] `agent_runs` role/model/thinking/token/cache telemetry
- [x] model_calls/tool_calls/retries/compactions/elapsed/selected skill 기록
- [x] `sessions.final_status` 영속화
- [x] `sessions.running` 영속화
- [x] 서버 시작 시 interrupted run reconcile
- [x] run crash 시 오류 메시지 history 저장
- [x] metrics summary/session API
- [x] success_rate / review_first_pass / debugger_activation / Pro escalation 집계
- [x] 모델 가격 설정 시 estimated cost 계산
- [x] bottleneck diagnostic rules
- [x] `docs/benchmark.md` 기준 작업 A~F

### 중요한 한계

서버 재시작 복구는 **중단된 run 감지 + 안내 + 상태 정리**까지다. model/tool 실행 stack을 이어서 실행하는 durable resume은 아직 아니다.

## 완료 — Durable 가시성 / Remote

- [x] SSE streaming
- [x] Agent `send()` 이벤트 JSONL durable log
- [x] `/sessions/{id}/status`
- [x] status에 `running`, `role`, `activity`, `waiting_for`, idle 정보
- [x] SSE 끊김 시 status polling으로 Mac 작업 상태 추적
- [x] tool/thinking/text activity 한 줄 표시
- [x] 승인/질문 대기 상태 재접속 표시
- [x] 앱 종료 후 서버 run 계속 + 완료 자동 새로고침

## 완료 — Mobile PWA

- [x] 세션 드로어 / 최근 세션 landing
- [x] 신규 session workspace 선택 필수
- [x] 채팅/추론/tool/diff 표시
- [x] 첨부 이미지 썸네일 + 전체화면 이미지 viewer
- [x] 실행 중 typing/activity 표시
- [x] 실행 중 context/복사 액션 숨김
- [x] Kanban live refresh 및 task 상태 전이 인라인 알림
- [x] Git changes/history/branch/file diff
- [x] 파일 브라우저 + hidden toggle + 타입별 아이콘
- [x] Session search
- [x] Skills viewer + collapsible 카드
- [x] 세션 사용량/효율 metrics UI
- [x] 4종 테마 + FORGE 로고/PWA 이름
- [x] iOS safe-area
- [x] history loading skeleton
- [x] PWA update 무한 reload 방지

## 아직 남은 핵심 작업

### 1. Durable Worker / 실제 Resume — 최우선

- [ ] Agent worker를 FastAPI request/process lifecycle에서 분리
- [ ] durable queue
- [ ] replay 가능한 authoritative event stream
- [ ] 서버 재시작 후 step/run continuation 실제 복원
- [ ] reconnect 시 필요한 event range replay

현재 JSONL event log는 감사/추적 계층이며 위 기능을 대체하지 않는다.

### 2. Tool 효율

- [ ] Tool Script/RPC Mode — 탐색성 다중 tool을 한 model round-trip으로 묶기
- [ ] AgentRuntime의 tool 정책/dispatch 코드가 더 커질 경우 ToolExecutor 분리

### 3. Persistent Automation

- [ ] Scheduled Jobs
- [ ] Condition Jobs
- [ ] Web Push

### 4. Execution Backend

- [~] Local execution — Docker 기본 + host 옵트인이 존재하지만 공통 Backend abstraction은 없음
- [ ] SSHBackend
- [ ] Docker/Host를 공통 ExecutionBackend interface로 정리(실제 필요 시)

### 5. 이후 검토

- [ ] isolated subagent
- [ ] MCP
- [ ] Repository Intelligence
- [ ] Vector Search

실제 benchmark로 병목이 확인되기 전에는 복잡한 프레임워크를 선제 도입하지 않는다.

## 현재 검증 세트

최근 `main`에서 다음이 통과한 상태로 보고됨.

- `test_review_loop.py`
- `test_runtime_efficiency.py`
- `test_metrics.py`
- frontend production build

## Proposal 반영 현황

상세 매핑은 [`proposal/README.md`](proposal/README.md)를 authoritative index로 사용한다.

### DeepSeek Harness

- [x] pruning / compaction / provider recovery / surface 분리
- [x] JSONL event logging 1차
- [~] durable resume/event replay — 미완료

### Claude Code clean-room

- [x] task lifecycle / approval boundary / runtime steering
- [~] coordinator/isolated worker — 미완료

### Hermes Agent

- [x] Self-Improving Skills / stable prefix / selective retrieval / session search
- [~] persistent runtime — 재접속은 지원, 서버 재시작 resume은 미완료
- [ ] Tool Script/RPC / scheduler / backend abstraction / subagent
