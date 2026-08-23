# FORGE — 시스템 아키텍처

> 기준: 2026-08-23 `main`

## 설계 중심

FORGE의 핵심은 저가 모델 선택이 아니라 **모델 위에 품질 보증 프로세스를 올리는 Harness**다.

```text
Vue3 PWA
  │ REST / SSE / event polling / WebSocket
  ▼
FastAPI Control Plane
  ├─ auth (`FORGE_AUTH_TOKEN`)
  ├─ Scheduler
  ├─ Mac Terminal/Screen/Camera
  └─ AgentRuntime
       ├─ Triage
       ├─ Chat
       ├─ Developer
       ├─ Context / Skills / Recovery
       ├─ Tool Executor
       └─ Strict Verification Gate
             ↓
     Docker(default) / Host(opt-in)
             ↓
 PostgreSQL + JSONL event log + Git
```

## Agent 흐름

```text
Request
 ↓
Triage ── CHAT → Chat
 │
 AGENT
 ↓
Developer (Flash + thinking)
 ↻ Plan → Execute → Self-verify/Repair
 ↓ 필요 시 Pro escalation
Strict Verification Gate
 ├─ test/build PASS → completed → commit/push 가능
 └─ FAIL → bounded repair → 재검증 → verification_failed
```

별도 Planner/Reviewer/Debugger를 기본 실행 경로에서 제거해 컨텍스트 재전송을 줄였다. 그러나 비용 절감보다 중요한 것은 **Developer의 결과를 모델 스스로 최종 승인하지 못하게 하고 프로세스 검증을 별도 authority로 둔 것**이다.

## Durable Execution

Agent step마다 history를 영속화한다. 서버 시작 시 unfinished/running session을 찾아 저장된 history 기반으로 headless resume한다.

- `AUTO_RESUME=0`으로 비활성화 가능
- resume 중 재충돌 시 무한 재개를 막는 guard 존재
- Python coroutine 자체를 복원하는 것이 아니라 저장된 Agent state/history에서 실행을 재구성한다.

resume 과정에서 approval 권한이 확대되지 않도록 capability 경계를 강화했다: 재시작 전 auto_approve 값을 그대로 복원(True 강제 없음), 세션별 승인 필터, BLOCKED_COMMANDS 차단. 회귀 테스트(`test_reliability_gates.py`·`test_reliability_invariants.py`)로 고정되어 있다.

## Verification Authority

최종 `completed`는 모델 발화가 아니라 `_verify()` 결과가 결정한다.

현재 자동 탐색 대상은 root/frontend의 npm build와 root/backend의 pytest 중심이다. 실패하면 1회 bounded repair 후 다시 검증한다.

현재 `_verify()`는 `PASSED / FAILED / UNAVAILABLE` 3상태를 반환한다. pytest exit 0=passed, 1=failed, 그 외(수집/설정 오류·timeout·미설치)=unavailable이며, unavailable은 성공으로 기록되지 않는다. 회귀 테스트(`test_reliability_gates.py`·`test_reliability_invariants.py`)로 고정되어 있다.

## Context / Skills

- prompt token pressure 기반 compaction/hard block
- tool result pruning
- stable prefix/cache telemetry
- reasoning 호환 오류 recovery
- Skills 3계층: Curated / Learned / Project
- 관련 Skill만 제한적으로 주입

## Persistence / Events

- PostgreSQL: sessions/messages/tasks/checkpoints/agent_runs 등
- JSONL: durable action/event log
- SSE: live stream
- eventlog polling + sequence dedup: proxy buffering/재접속 보완
- status polling: foreground 복귀 및 stale UI reconcile

## Benchmark / RSI

`backend/bench.py` + `bench_tasks.py`가 격리 fixture와 deterministic checker로 R0 평가를 수행한다. 현재 21개 task가 있다.

`backend/rsi.py`는 baseline/candidate 결과를 `success_rate → cost_per_success → elapsed` 순으로 비교하는 promotion gate를 구현한다. candidate worktree 실행과 merge는 아직 자동화하지 않으며 사람 승인을 유지한다.

## Tool / Execution

읽기/수정/bash/build_frontend/Git 계열 도구를 사용한다. Docker가 기본이며 Host는 명시적 opt-in이다. Host mode와 Terminal은 높은 신뢰 경계로 취급한다.

## Remote Operation

PWA 정보구조는 세션 / 예약 / 맥 중심이다.

- Agent activity / approval / steering
- Git / Files / Skills / Metrics / Kanban
- Mac host PTY Terminal
- view-only Screen
- Camera JPEG polling PoC
- Scheduled Job 기반

## 보안

HTTP와 WebSocket `/api/*`는 `FORGE_AUTH_TOKEN` 기반 application auth를 사용한다. Zero Trust/VPN은 추가 방어층이지 application auth 대체물이 아니다.

## 다음 구조적 과제

1. benchmark 확대
2. RSI candidate worktree + benchmark + human promotion
3. Scheduler durable semantics
4. Tool Script/RPC
5. ExecutionBackend(Local/Docker/SSH)
