# FORGE — 시스템 아키텍처

> 기준: 2026-08-22 `main`

## 전체 구조

```text
Vue3 PWA (Mobile/Desktop)
        │ SSE + REST + status polling
        ▼
FastAPI
        │
        ▼
AgentRuntime (현재 API 프로세스 내부)
  ├─ Triage
  ├─ Planner
  ├─ Coder
  ├─ Reviewer ↔ Debugger
  ├─ Context/Compaction/Recovery
  └─ Tool Executor
        │
        ├─ DeepSeek V4 Adapter
        ├─ Execution: Docker(default) / Host(opt-in)
        └─ PostgreSQL

보조 지속성:
- JSONL durable event/action log
- sessions.running 플래그
- metrics/agent_runs
```

Redis 컨테이너는 존재하지만 현재 Agent event replay/worker queue의 authoritative 경로로 사용하지 않는다. Worker 분리와 Redis Streams 기반 durable resume은 미래 과제다.

## 실행 흐름

```text
Request
 ↓
Triage ── CHAT → Chat Flash → Done
 │
 AGENT + SIMPLE/COMPLEX
 ↓
Planner
  SIMPLE  → Flash + thinking medium
  COMPLEX → Pro + thinking high
 ↓
Coder Flash
 ↓
Reviewer Flash
 ↓
all tasks done? ── yes → completed
 ↓ no
Debugger Flash
 ↓ 반복 실패 마지막 복구
Debugger Pro
 ↓
Reviewer 재검증
```

DB task 상태가 성공 판정의 authority다. 최대 자기수정 사이클은 3회다.

## Context / 비용 구조

- context pressure는 provider 실측 `prompt_tokens` 기준
- 75% 초과 시 오래된 model surface를 Flash로 요약(compaction)
- compaction 성공 직후 압축 전 usage로 차단하지 않고 다음 호출에서 재실측
- 95% 초과이면서 더 줄일 수 없을 때 hard block
- 긴 tool result는 head/tail/오류 중심으로 pruning
- 원본 conversation history와 model projected context는 분리
- stable prefix: BASE_PROMPT + role instructions
- dynamic tail: memory + selected skills + conversation
- cache hit/miss와 prefix hash를 계측

## Skill / Memory

`.forge/skills/*.md`는 모두 prompt에 넣지 않는다. 현재 요청과 키워드 겹침으로 상위 최대 3개, 총 6000자 예산 내에서 선택한다. `save_skill`은 승인 게이트를 통과한다.

## Provider Recovery

- `reasoning_content` 계약 오류: reasoning 제거 + thinking off 재시도
- 429/5xx/timeout/connection: 1/2/4초 backoff, 최대 3회
- 일부 delta가 이미 사용자에게 전달된 뒤 실패한 stream은 중복 생성을 막기 위해 재시도하지 않는다.

## Tool / Execution

읽기 전용 `read_file/list_dir/grep` 다중 호출은 병렬 prefetch 가능하다. `write_file/edit_file/bash/save_skill`은 승인 대상이며 변경 전 git SHA checkpoint를 기록한다.

### Docker mode — 기본

`SANDBOX_MODE=docker`가 기본값이다. bash를 제한된 Docker 환경에서 실행해 non-root/resource isolation을 유지한다.

### Host mode — 명시적 옵트인

`SANDBOX_MODE=host`는 bash를 호스트에서 직접 실행한다. Agent가 FORGE 자신의 개발/검증이나 로컬 도구를 더 자유롭게 사용할 수 있지만 격리가 사라지므로 신뢰된 개인 환경에서만 사용한다. `/workspace` 경로는 실제 세션 workspace로 치환된다.

파일 브라우저 API는 실행 모드와 별개로 session workspace 경계를 강제해 지정 workspace 밖 접근을 차단한다.

## Remote Operation

- SSE: 실시간 thinking/text/tool/task/diff 이벤트
- `/sessions/{id}/status`: `running`, 현재 `role`, `activity`, `waiting_for`, idle 상태 조회
- SSE가 끊겨도 PWA는 status polling으로 진행 상황을 추적
- 승인/질문은 최대 600초 대기 후 안전하게 종료
- cancel 시 pending approval/question future를 해제
- 모든 send 이벤트는 JSONL event log에 기록
- 첨부 이미지는 채팅 썸네일로 표시하고 전체화면 viewer에서 확인 가능
- Skills viewer는 카드 단위 collapsible UI 제공

### 서버 재시작

`sessions.running=true`로 남은 세션을 시작 시 reconcile해 중단 사실을 메시지로 남기고 플래그를 정리한다. 이는 **중단 감지/복구 안내**이며, 실행 stack을 복원해 이어서 실행하는 durable resume은 아니다.

## Telemetry

`agent_runs`와 metrics 집계를 통해 role/model별 token, cache, model/tool call, retry, compaction, elapsed, selected skill, Pro 승격 등을 기록한다.

API:

- `GET /api/metrics/summary`
- `GET /api/rooms/{id}/metrics`

성공 정의의 기본값은 `final_status == completed`이며 핵심 최적화 지표는 `cost per successfully completed task`다.

## 현재 데이터 계층

- PostgreSQL: sessions/messages/tasks/checkpoints/agent_runs 및 실행 상태/metrics 영속화
- JSONL: durable action/event log
- Redis: 컨테이너 구성됨, durable Agent queue/replay는 미연결

## 다음 구조적 과제

1. Agent worker를 API 프로세스와 분리
2. durable queue + event replay
3. 서버 재시작 후 실제 run resume
4. Tool Script/RPC Mode
5. Scheduled/Condition Jobs + Web Push
6. ExecutionBackend(Local/SSH/Docker)
