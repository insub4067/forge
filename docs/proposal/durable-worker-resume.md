# Durable Worker / Resume 제안

> 상태: Proposal
> 목표: API 프로세스 재시작·크래시가 진행 중인 agent run을 잃지 않도록, 실행 상태를
> 체크포인트로 영속화하고 재개(resume)한다. 외부 정적 분석이 지적한 최대 reliability gap.

## 1. 문제

`AgentRuntime`은 API(FastAPI) 프로세스 안에서 `asyncio.create_task()`로 돈다. 즉
**API 실패 도메인과 Agent 실패 도메인이 같다.** uvicorn을 재시작하거나 프로세스가 죽으면
진행 중이던 run은 통째로 사라진다.

현재 있는 것과 없는 것:

- `checkpoints` 테이블: `session_id, git_sha, step_no, created_at`만 — **마커일 뿐** 실행 상태(all_messages·현재 role·state dict)를 담지 않아 재개 불가.
- `reconcile_interrupted_runs()`: 재시작 시 `running=True`로 남은 세션을 찾아 플래그를 내리고 "서버가 재시작되어 중단됨" 안내만 남긴다 — **재개가 아니라 정리·통보**.
- `messages/tasks/agent_runs`는 결과를 기록하지만 실행 stack은 복원 못 한다.

2026년 harness 흐름(OpenAI Agents SDK의 harness/compute 분리·state 외부화, LangGraph의
durable execution·resume)의 핵심은 **state를 외부화하면 실행 환경이 사라져도 checkpoint에서
복원**할 수 있다는 것이다. FORGE는 관측(telemetry)은 훌륭하나 실행 durability가 비어 있다.

## 2. 원칙

- **의존성 추가 없이 불변조건만 차용**: LangGraph를 넣지 않는다. checkpointable state,
  idempotent node, resumability 세 가지 불변조건만 자체 runtime에 적용한다.
- **비용 원칙 유지**: 체크포인트 오버헤드는 무시 가능해야 한다 — role 경계마다 JSON 1회
  저장이지, 토큰마다·툴콜마다가 아니다. `cost per successfully completed task`를 악화시키지 않는다.
- **가장 작은 구조**: FORGE 파이프라인은 이미 자연스러운 node 경계를 가진다 —
  `Triage → (Planner) → Coder → Reviewer ↔ Debugger`. 각 role step이 checkpoint 지점이다.
  `all_messages`와 `state`가 곧 run state이므로, 경계에서 그걸 저장하면 된다.

## 3. Run 상태 스냅샷 (D0)

role 경계에서 재개에 필요한 최소 상태를 저장한다.

```text
run_state(session_id):
  phase            다음 실행할 role (triage|planner|coder|reviewer|debugger|done)
  step_base        현재 step_base
  review_cycle     reviewer 루프 카운터
  debug_attempts   debugger 재시도 수
  state            {goal, files_changed, errors}
  git_sha          workspace HEAD (재개 시 코드 정합성 확인용)
  updated_at
```

`all_messages`는 이미 `save_history`로 영속화되므로 스냅샷에는 참조만 둔다(중복 저장 안 함).
`checkpoints` 테이블을 확장하거나 `session`에 `run_state JSON` 컬럼을 idempotent ALTER로
추가한다(기존 `_COLUMN_PATCHES` 패턴 재사용). 저장은 각 `_run_role` 완료 직후 1회.

## 4. 재개 (D1)

재시작 시 `reconcile_interrupted_runs`를 **정리에서 재개로** 확장한다.

```text
running=True 세션 발견
  → run_state 로드
  → git_sha 일치 확인(불일치면 재개 대신 안내)
  → 기록된 phase부터 파이프라인 재진입
  → (재개 불가·비활성화 시) 기존처럼 안내 메시지
```

**idempotent 재진입**: 마지막 미완료 role은 처음부터 다시 실행한다. role은 `all_messages` +
디스크 workspace(영속) 위에서 동작하므로 재진입이 대체로 안전하다. 남는 위험은 **이미 실행된
mutation tool의 중복**(예: write_file 두 번). 1차 구현은 role 단위 재진입(중복 가능성 수용,
대개 idempotent한 파일 쓰기)으로 시작하고, 필요하면 tool-call 단위 체크포인트로 세분화한다.

기본값은 **opt-in**: `FORGE_RESUME=1`일 때만 재개, 아니면 현재의 안전한 정리·통보 유지.
자동 재개가 무한 루프·비용 폭주를 부를 수 있으므로 재개 횟수 상한을 둔다.

## 5. Worker 분리 (D2 — 이후)

D0/D1로 재개가 신뢰되면, 실행을 별도 worker 프로세스로 옮겨 **API 실패 도메인과 분리**한다
(OpenAI SDK의 harness/compute 분리).

```text
API  → run 요청을 큐에 넣음(이미 있는 Redis 활용)
Worker → 큐에서 claim → 실행 → 상태를 DB에 체크포인트
```

API가 재시작돼도 worker의 run은 계속되고, worker가 죽어도 다른 worker가 checkpoint에서
이어받는다. 이 단계는 별도 프로세스·큐 관리가 필요하므로 D0/D1 이후로 미룬다.

## 6. Scheduler claim (D3 — 이후)

현재 scheduler는 API 프로세스 안 20초 폴링이다. worker가 여럿이 되면 같은 job을 동시에
실행할 수 있으므로 **leader-election 또는 DB row claim**(`UPDATE ... WHERE status='scheduled'
RETURNING`)이 필요하다. 단일 프로세스에서는 불필요하므로 D2 이후.

## 7. 단계

| 단계 | 내용 | 규모 |
|---|---|---|
| **D0** | role 경계 run_state 스냅샷 저장 | 작음 — 컬럼 1개 + `_run_role` 후 저장 |
| **D1** | 재시작 시 opt-in 재개(idempotent 재진입, 상한) | 중간 — reconcile 확장 |
| D2 | worker 프로세스 분리 + Redis 큐 | 큼 — 이후 |
| D3 | scheduler claim(멀티 worker) | 중간 — D2 이후 |

**D0+D1만으로도** 단일 프로세스에서 "재시작해도 이어서 완료"가 되어 신뢰성이 크게 오른다.

## 8. 하지 않을 것

- LangGraph·외부 orchestration 프레임워크 의존
- 전체 event-sourcing replay(모든 이벤트 재생) — 무겁다
- 토큰·툴콜 단위 체크포인트(1차) — role 경계면 충분
- 자동 무한 재개 — 상한·opt-in 필수
- 분산 worker를 D0 이전에 도입

## 9. 완료 기준

1. role 경계에서 run_state가 영속화된다(오버헤드 무시 가능).
2. API 재시작 후 `FORGE_RESUME=1`이면 진행 중이던 run이 기록된 phase부터 이어서 완료된다.
3. git_sha 불일치·상한 초과 시 안전하게 정리·통보로 폴백한다.
4. 재개가 중복 mutation으로 결과를 오염시키지 않는다(또는 그 위험이 문서화·상한된다).
5. 체크포인트가 `cost per successfully completed task`를 악화시키지 않는다.
6. bench(R0)로 재개 on/off의 성공률·비용 회귀가 없음을 확인한다.

## 결론

FORGE의 다음 신뢰성 도약은 모델이 아니라 **실행 상태의 외부화**다.

> role 경계 체크포인트(D0) → opt-in 재개(D1) → worker 분리(D2) → scheduler claim(D3)

의존성 없이 checkpointable·idempotent·resumable 세 불변조건만 자체 runtime에 심는다.
가장 먼저 할 일은 **D0 — role 경계 run_state 스냅샷**이고, 이것만으로 재개의 토대가 선다.
