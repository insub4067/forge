# Claude Code 설계 패턴 Clean-Room 도입 제안

> 목적: Claude Code의 유출 코드나 비공개 구현을 직접 복제하지 않고, 공개된 분석 자료와 외부에서 관찰 가능한 동작을 바탕으로 FORGE에 유용한 설계 패턴만 독립적으로 재구현한다.

## 1. 배경

FORGE는 저비용 DeepSeek 계열 모델을 반복 호출하면서 실제 코드베이스를 탐색·수정·검증하는 장시간 실행형 코딩 에이전트를 목표로 한다.

현재 FORGE는 Triage, Planner, Coder, Reviewer, Debugger, Vision, tool calling, 승인 게이트, 실행 중 메시지 주입, cancel, git checkpoint/diff, 모바일 PWA 등을 갖추고 있다.

다음 단계의 핵심은 모델 자체의 성능보다 Harness 품질이다. 장시간 작업에서 중요한 것은 다음과 같다.

- 세션이 오래 살아남는가
- 컨텍스트를 안정적으로 관리하는가
- 실패 후 스스로 복구하는가
- 사용자가 작업 중 방향을 바꿀 수 있는가
- 작업을 안전하게 분할·병렬화할 수 있는가
- 서버/클라이언트 재접속 이후에도 상태를 복원할 수 있는가

Claude Code에서 공개적으로 관찰·분석된 설계 패턴 중 이 문제를 잘 푸는 요소를 FORGE 방식으로 재구현한다.

---

## 2. 원칙

### 2.1 Clean-Room 원칙

다음은 금지한다.

- Anthropic 비공개 소스 직접 복사
- 유출된 코드의 함수/클래스 구현을 그대로 포팅
- 고유 명칭·내부 문자열·프롬프트를 그대로 재사용
- 출처가 불명확한 비공개 코드 조각 도입

허용 범위는 다음과 같다.

- 공개 문서와 공개 분석 자료에서 확인되는 일반적인 아키텍처 패턴
- 외부 동작을 통해 확인 가능한 제품 기능
- 업계에서 널리 사용되는 상태 머신, inbox, retry, task graph, permission layer 등의 개념
- FORGE 요구사항에 맞춘 독립 구현

목표는 Claude Code 복제가 아니라 FORGE의 Harness 품질 강화다.

### 2.2 과설계 금지

Claude Code 전체 구조를 따라 하지 않는다.

특히 초기 단계에서는 다음을 만들지 않는다.

- 거대한 plugin framework
- 복잡한 dependency injection container
- 범용 workflow DSL
- 불필요한 multi-agent hierarchy
- 대규모 MCP abstraction

현재 Python/FastAPI 기반 구조를 최대한 유지한다.

---

## 3. 도입 우선순위

| 우선순위 | 기술 | 기대 효과 |
|---|---|---|
| S | Task lifecycle/state machine | 자율 반복 작업의 기준 상태 확립 |
| S | Steer / Follow-up / Interrupt inbox | 모바일 원격 제어 품질 향상 |
| S | Provider retry/recovery | 장시간 실행 안정성 |
| S | Context layering + compaction 연계 | 장시간 세션 지속 |
| A | Tool permission pipeline | 안전성과 확장성 |
| A | Cooperative cancellation | 원격 중단 신뢰성 |
| A | Durable event log / resume | 재접속·서버 재시작 복구 |
| B | Coordinator + isolated workers | 복잡한 작업 분할 |
| B | Parallel-safe tool execution | 탐색 속도 향상 |
| B | Skills | 상황별 전문화, 프롬프트 비용 절감 |
| C | Background/scheduled tasks | CI 재확인 등 장기 워크플로 |

---

## 4. Task Lifecycle을 단순 체크리스트에서 실행 상태로 승격

현재 `update_tasks`는 주로 UI/진행 표시 역할에 가깝다.

향후 task를 Agent Runtime의 authoritative orchestration state로 사용한다.

권장 상태:

```text
pending
ready
running
review
blocked
debug
done
failed
cancelled
```

최소 구조 예시:

```python
Task(
    id,
    title,
    status,
    depends_on=[],
    attempts=0,
    error=None,
    result=None,
)
```

핵심 규칙:

- dependency가 모두 `done`이면 `ready`
- 실행 시작 시 `running`
- 코드 수정 완료 후 `review`
- Reviewer 결함 발견 시 `debug`
- 해결 불가 시 `failed`
- 사용자 중단 시 `cancelled`

이렇게 하면 Planner → Coder → Reviewer라는 고정 파이프라인을 넘어 상태 기반 loop로 발전시킬 수 있다.

```text
Planner
  ↓
Task Graph
  ↓
ready task 실행
  ↓
review/debug 상태 확인
  ↓
필요한 agent 호출
  ↓
모든 task done?
  ├─ yes → complete
  └─ no  → continue
```

---

## 5. Steer / Follow-up / Interrupt 구분

모바일 원격 제어의 핵심 기능이다.

현재의 단일 injection 개념을 다음 세 가지로 명확히 나눈다.

### Follow-up

현재 turn은 그대로 진행한다.

새 요청은 다음 turn의 FIFO queue에 들어간다.

예:

> 이거 끝나면 README도 업데이트해.

### Steer

현재 turn을 중단하지 않고 다음 model/tool step부터 즉시 반영한다.

예:

> 방금 파일 말고 service.py부터 확인해.

### Interrupt

현재 실행을 cancel하고 새 요청으로 새 turn을 시작한다.

예:

> 중단해. DB 마이그레이션은 건드리지 마.

권장 구조:

```text
Session Inbox
├─ next_turn[]
└─ next_step[]
```

각 메시지는 최소한 다음을 가진다.

```text
id
mode
content
created_at
status
```

중요한 점은 inbox 변경을 메모리에만 두지 않고 durable event로 기록하는 것이다.

---

## 6. Provider Retry / Recovery 계층

LLM API 오류와 Agent 논리 실패를 분리한다.

예상 오류 정책:

```text
429
→ exponential backoff
→ retry

5xx / connection reset
→ retry

context overflow
→ prune/compact
→ retry

invalid request / unsupported tool schema
→ terminal

401 / 403
→ terminal
```

권장 인터페이스:

```python
RecoveryDecision = (
    RETRY
    | COMPACT_AND_RETRY
    | FAIL
)
```

AgentRuntime 내부 곳곳에서 예외를 처리하지 말고 adapter 또는 별도 recovery policy를 통해 판단한다.

retry 자체도 session event로 남긴다.

```text
llm/request_failed
llm/retry_scheduled
llm/retry_started
```

이를 통해 모바일에서도 "멈춘 것"과 "복구 중"을 구분할 수 있다.

---

## 7. Context Layering

모든 정보를 항상 system prompt에 넣지 않는다.

FORGE context를 계층화한다.

```text
Layer 1: Base Runtime Prompt
Layer 2: Agent Role
Layer 3: Global Memory
Layer 4: Workspace / Room Memory
Layer 5: Active Task State
Layer 6: Session Surface
Layer 7: Temporary Injected Context
```

각 계층은 독립적으로 조립된다.

특히 다음을 구분한다.

- 영구 지침
- 프로젝트 지식
- 현재 세션 기록
- 현재 task 상태
- 일시적인 사용자 steering

DeepSeek Harness 도입안의 compaction과 결합한다.

```text
Context pressure
   ↓
tool result pruning
   ↓
old history compaction
   ↓
active task + recent tail 유지
   ↓
계속 실행
```

단순히 95%에서 session을 종료하는 구조에서 벗어난다.

---

## 8. Tool Permission Pipeline

현재 AgentRuntime에 섞여 있는 승인·checkpoint·실행·결과 처리를 분리한다.

권장 pipeline:

```text
validate
  ↓
permission decision
  ↓
guard
  ↓
checkpoint
  ↓
dispatch
  ↓
normalize result
  ↓
post policy
  ↓
observe/persist
```

Permission 결과:

```text
allow
ask
deny
```

향후 Worker마다 서로 다른 tool capability를 부여할 수 있게 한다.

예:

```text
Reviewer
→ read_file / grep / bash(test only)
→ write_file 금지

Coder
→ read/write/edit/bash

Research Worker
→ read/grep only
```

권한 제어는 모델 프롬프트에만 의존하지 않고 Runtime이 강제해야 한다.

---

## 9. Cooperative Cancellation

현재 step 경계에서만 cancel 여부를 검사하면 긴 bash나 API stream 중 즉시 멈추지 못할 수 있다.

취소 신호를 하위 실행 계층까지 전달한다.

```text
session cancel
  ↓
current turn cancellation token
  ├─ LLM HTTP stream close
  ├─ subprocess terminate
  ├─ tool execution cancellation
  └─ worker cancellation
```

중요 원칙:

- 실행 전 취소와 실행 중 취소를 구분
- 이미 시작한 리소스를 정리한 뒤 종료
- 중단된 상태를 session log에 기록
- 모바일 UI가 종료 이유를 정확히 표시

종료 상태 예:

```text
cancelled_by_user
cancelled_by_interrupt
disposed
timeout
```

---

## 10. Durable Event Log와 Model Surface 분리

Session의 모든 사건을 LLM context에 넣지 않는다.

### Durable Event Log

```text
session/created
turn/start
user/message
assistant/chunk
assistant/message
tool/call
tool/result
task/update
approval/request
approval/result
agent/steer
llm/retry
compaction/start
compaction/end
turn/end
session/end
```

### Model Surface

모델이 실제로 보는 것은 필요한 것만 projection한다.

```text
system
user messages
assistant final messages
tool calls/results
compaction summary
active task context
```

stream chunk, UI event, lifecycle 이벤트는 모델에게 보내지 않는다.

장점:

- 서버 재시작 후 replay 가능
- 모바일 재접속 가능
- 디버깅 용이
- context 관리 명확
- UI와 agent protocol 분리

---

## 11. Coordinator + Isolated Worker

기초 런타임이 안정된 뒤 도입한다.

Coordinator는 직접 모든 작업을 수행하지 않고 복잡한 목표를 독립 작업으로 나눈다.

예:

```text
User Goal
   ↓
Coordinator
   ├─ Worker A: API 구조 분석
   ├─ Worker B: frontend 영향 분석
   └─ Worker C: 테스트 분석
          ↓
      Results
          ↓
Coordinator
          ↓
Implementation Task
```

중요 원칙:

### Worker는 전체 세션을 그대로 받지 않는다.

Coordinator가 self-contained task packet을 만든다.

```text
goal
workspace
relevant context
allowed tools
expected output
budget
```

이렇게 해야 Worker 컨텍스트가 작고 독립적이다.

### 초기에는 1-depth만 허용한다.

Worker가 다시 Worker를 무제한 생성하지 못하게 한다.

```text
Coordinator
→ Worker
```

까지만 구현한다.

---

## 12. Parallel-safe Tool Execution

파일 탐색과 검색은 병렬 처리할 가치가 높다.

예:

```text
read_file A ─┐
read_file B ─┼─ parallel
read_file C ─┘
```

반면 상태 변경 도구는 exclusive하게 실행한다.

```text
write_file
edit_file
bash mutation
git checkout
git commit
```

Tool definition에 다음과 같은 속성을 추가할 수 있다.

```python
concurrency = "safe" | "exclusive"
```

또는 arguments를 보고 동적으로 판단한다.

초기 병렬 한도는 3~5 정도로 작게 시작한다.

---

## 13. Skills

Role과 Skill을 분리한다.

Role은 Agent가 누구인지 정의한다.

```text
planner
coder
reviewer
debugger
```

Skill은 특정 작업을 수행하는 지침 묶음이다.

```text
git-review
ios-build-debug
fastapi-debug
frontend-accessibility
oracle-sql-review
```

Skill에는 다음만 포함한다.

```text
instructions
tool restrictions
optional reference docs
```

필요한 skill만 context에 로드한다.

이를 통해 system prompt가 계속 커지는 것을 막는다.

---

## 14. Background / Deferred Task

Phase 후반 기능이다.

에이전트가 작업을 완료한 뒤 외부 상태를 다시 확인해야 하는 경우가 있다.

예:

```text
PR push
→ CI 실행 대기
→ CI 확인
→ 실패하면 수정
```

또는:

```text
배포
→ health check
→ 문제 있으면 rollback/report
```

FORGE 서버 내부 scheduler 또는 Redis queue와 연동할 수 있다.

단, 일반 코드 작업 loop가 안정되기 전에는 구현하지 않는다.

---

## 15. FORGE 목표 아키텍처

```text
Mobile PWA
    │
    │ command / steer / interrupt
    ▼
FastAPI Control Plane
    │
    ▼
Session Runtime
├─ Durable Event Log
├─ Inbox
├─ Task State
├─ Context Builder
└─ Cancellation Controller
    │
    ▼
Agent Orchestrator
├─ Triage
├─ Planner
├─ Coder
├─ Reviewer
├─ Debugger
└─ Coordinator (later)
    │
    ▼
LLM Router
├─ DeepSeek V4 Pro
├─ DeepSeek V4 Flash
└─ Vision
    │
    ▼
Tool Runtime
├─ permission
├─ guard
├─ checkpoint
├─ executor
├─ concurrency
└─ result normalization
    │
    ▼
Workspace / Docker Sandbox
```

---

## 16. 구현 순서

### Stage 1 — Runtime reliability

1. Provider retry/recovery
2. Cooperative cancellation
3. 종료 상태 명확화
4. Context pressure 계측 정리

완료 조건:

- 일시적인 API 장애 때문에 session 전체가 죽지 않는다.
- 긴 bash 실행 중에도 사용자 cancel이 동작한다.

### Stage 2 — Long-running session

1. Durable event log 정리
2. Model surface projection
3. Tool result pruning
4. Context compaction
5. resume/replay

완료 조건:

- context pressure가 올라가도 세션이 자동으로 축약되어 계속 실행된다.
- 서버 재기동 이후 세션 상태를 복원할 수 있다.

### Stage 3 — Mobile steering

1. Inbox persistence
2. follow-up
3. steer
4. interrupt
5. UI 상태 표시

완료 조건:

- 모바일에서 진행 중인 Agent의 방향을 안정적으로 바꿀 수 있다.

### Stage 4 — Task orchestration

1. Task ID/state/dependency
2. state-driven reviewer/debug loop
3. failure attempts
4. task-level budget

완료 조건:

- 고정 Agent 순서가 아니라 task 상태에 따라 다음 행동을 결정한다.

### Stage 5 — Tool runtime

1. ToolExecutor 분리
2. permission/guard pipeline
3. timeout
4. parallel-safe reads

완료 조건:

- AgentRuntime이 tool 세부 정책을 직접 처리하지 않는다.

### Stage 6 — Coordinator

1. task decomposition
2. isolated worker context
3. worker tool restrictions
4. parallel workers
5. result aggregation

완료 조건:

- 독립 분석 작업을 여러 Worker에 분산할 수 있다.

### Stage 7 — Skills / background workflows

제품 필요성이 생길 때만 추가한다.

---

## 17. 성공 기준

Claude Code와 기능 개수를 비교하지 않는다.

FORGE의 성공 기준은 다음이다.

### Reliability

- 일시적인 API 오류에서 자동 복구
- 무한 loop 차단
- context overflow 자동 복구
- tool 실행 중 cancel 가능

### Cost

- 단순 작업은 Flash 중심
- 고난도 판단에서만 Pro 승격
- context pruning/compaction으로 반복 입력 비용 감소
- 독립 Worker에는 필요한 정보만 전달

### Remote UX

- 모바일에서 작업 상태 확인
- steer 가능
- interrupt 가능
- 승인 가능
- 재접속 후 현재 작업 복구

### Coding Quality

- 작업을 계획하고 실행
- 테스트/빌드로 검증
- 결함 발견 시 수정 후 재검증
- 해결 불가 시 명확한 실패 보고

---

## 18. 비목표

당분간 다음을 목표로 하지 않는다.

- Claude Code UI 복제
- Anthropic 내부 구조 1:1 재현
- 모든 기능의 plugin화
- 무제한 multi-agent
- 범용 workflow engine
- IDE 자체 구현

FORGE의 핵심은 계속 다음이다.

> 저비용 모델을 강한 Harness 위에서 반복 실행하고, 모바일에서 장시간 원격 제어할 수 있는 코딩 에이전트.

Claude Code에서 가져올 것은 외형이 아니라 장시간 작업을 버티게 만드는 운영 원리다.

---

## 19. 법적·개발 원칙

공개적으로 유출되었거나 제3자가 복원한 Anthropic 코드가 존재하더라도 그것이 오픈소스가 된 것은 아니다.

따라서 FORGE에서는 해당 코드를 직접 dependency로 사용하거나 복사하지 않는다.

구현자는 이 문서의 기능 요구사항과 공개적으로 알려진 일반 설계 개념만을 기준으로 독립 구현한다.

코드 리뷰 시에도 Claude Code 내부 구현과의 문장·식별자·구조적 동일성을 목표로 하지 않는다.

이 정책은 향후 FORGE를 공개하거나 상용화할 가능성을 고려한 기본 원칙으로 유지한다.
