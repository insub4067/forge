# DeepSeek Harness 기술 도입 제안

> 대상: FORGE
> 참고 구현: `deepseek-ai/deepseek-harness`
> 작성일: 2026-08-22

## 1. 목적

FORGE는 저비용 LLM을 반복 호출해 실제 코드베이스에서 장시간 문제를 해결하는 셀프호스팅 코딩 에이전트를 목표로 한다.

현재 FORGE는 Triage → Planner → Coder → Reviewer → Debugger 역할 파이프라인, Tool Calling, 승인 게이트, SSE 스트리밍, 모바일 PWA, Git 추적, 실행 중 사용자 메시지 주입 등을 갖추고 있다.

다음 단계의 핵심 문제는 새로운 역할을 더 만드는 것이 아니라 에이전트가 오랫동안 실행되어도 다음 특성을 유지하는 것이다.

- 컨텍스트가 커져도 작업을 중단하지 않고 계속 진행할 수 있어야 한다.
- 서버 또는 클라이언트가 끊겨도 실행 상태를 복구할 수 있어야 한다.
- 모델 API 실패가 전체 Agent Runtime 실패로 이어지지 않아야 한다.
- 실행 중 사용자가 모바일에서 작업 방향을 안전하게 수정할 수 있어야 한다.
- Tool 실행이 승인, 취소, timeout, 결과 정규화 등의 정책과 분리되어야 한다.

DeepSeek Harness는 이 문제들을 해결하기 위한 상당히 성숙한 실행 구조를 이미 가지고 있다. FORGE는 Harness 전체를 복제하지 않고, 장시간 실행 안정성에 직접 기여하는 설계만 선택적으로 도입한다.

---

## 2. 핵심 결론

FORGE에 가장 가치가 높은 도입 대상은 다음 순서다.

| 우선순위 | 기술 | 기대 효과 |
|---|---|---|
| S | Tool Result Pruning + Context Compaction | 장시간 작업 지속 |
| S | Durable Event Log와 Model Surface 분리 | 복구·재접속·컨텍스트 제어 |
| S | Provider Error Recovery | API 장애에도 Agent Loop 유지 |
| A | Followup / Steer / Inject Inbox | 모바일 원격 제어 강화 |
| A | Cooperative Cancellation | 실행 중 즉시 중단 및 정리 |
| A | Tool Execution Pipeline | AgentRuntime 단순화·안전성 향상 |
| B | Parallel-safe Tool Execution | 탐색 작업 속도 개선 |
| B | Code Mode | LLM 호출 횟수 및 비용 절감 가능성 |
| C | 범용 Plugin Framework | 현재 FORGE에는 과설계 |

가장 먼저 구현할 것은 **Context Compaction**이다.

FORGE의 현재 전략이 컨텍스트 한도에 도달하면 중단하는 방식이라면, 목표 구조는 다음과 같아야 한다.

```text
Context Pressure
      ↓
Tool Result Pruning
      ↓
충분히 감소?
  ├─ Yes → 계속 실행
  └─ No
      ↓
History Compaction
      ↓
오래된 작업을 Summary Checkpoint로 치환
      ↓
계속 실행
```

---

## 3. Context Compaction

### 3.1 현재 문제

장시간 Agent Loop에서는 다음 데이터가 계속 누적된다.

- 사용자 요청
- Planner 출력
- Coder 출력
- Reviewer 출력
- Debugger 출력
- read_file 결과
- grep 결과
- bash 출력
- tool call / result
- 수정 후 재검증 결과

Reviewer → Debugger → Reviewer 루프가 강화될수록 컨텍스트 증가 속도는 더 빨라진다.

단순히 95%에서 실행을 중단하면 FORGE가 목표로 하는 장시간 자율 작업과 충돌한다.

### 3.2 제안 구조

컨텍스트 관리는 두 단계로 한다.

#### Step 1 — Model-free Tool Result Pruning

모델 호출 없이 지나치게 긴 tool result를 축약한다.

예:

```text
원본 bash output
[앞부분]
...
수천 줄
...
[마지막 에러]
```

을 다음처럼 바꾼다.

```text
[앞 100줄 유지]

... 7,842 characters pruned ...

[뒤 100줄 유지]
```

권장 대상:

- bash output
- grep 결과
- 대형 read_file 결과
- 빌드 로그
- 테스트 로그

보존 우선순위:

1. 처음 부분
2. 오류 또는 경고 라인
3. 마지막 부분
4. 전체 길이와 생략량 메타데이터

#### Step 2 — Summary Compaction

Pruning 이후에도 context pressure가 높으면 오래된 history 구간을 요약한다.

예:

```text
User
Planner
Tool
Tool
Coder
Tool
Reviewer
Debugger
```

를 다음 checkpoint 하나로 치환한다.

```text
[COMPACTION CHECKPOINT]

목표:
- 로그인 세션 복구 문제 수정

확인한 사실:
- auth.py에서 refresh token 검증 누락
- frontend store가 401에서 세션을 제거함

변경한 파일:
- backend/app/auth.py
- frontend/src/store/auth.js

남은 작업:
- integration test 실행
- Reviewer 재검증

중요한 실패:
- test_refresh_expired 실패
```

### 3.3 Compaction 안전 조건

Tool call과 Tool result의 관계를 깨뜨리면 안 된다.

다음처럼 tool result만 남는 상태는 금지한다.

```text
Tool Result B
Tool Result C
```

원래 대응하는 assistant tool call이 제거됐다면 모델 프로토콜이 깨질 수 있다.

따라서 compaction 범위는 반드시 tool call/result pair가 완결된 경계만 선택한다.

### 3.4 권장 모듈

초기 구현은 과도한 abstraction 없이 다음 정도면 충분하다.

```text
backend/app/context/
├── meter.py
├── pruner.py
└── compactor.py
```

예상 인터페이스:

```python
class ContextManager:
    async def compact_if_needed(
        self,
        messages: list[dict],
        current_tokens: int,
        context_limit: int,
    ) -> list[dict]:
        ...
```

### 3.5 Trigger

권장 임계값:

```text
< 70%   정상
70~85%  tool result pruning 후보
85~92%  자동 compaction
> 92%   강제 compaction / recovery
```

정확한 비율은 실제 DeepSeek context window와 telemetry를 기준으로 조정한다.

---

## 4. Durable Event Log와 Model Surface 분리

### 4.1 핵심 아이디어

FORGE 내부의 모든 실행 기록과 모델에게 보내는 메시지를 동일한 배열로 취급하지 않는다.

다음 두 계층으로 분리한다.

```text
Durable Session Event Log
        ↓ projection
Model Surface
```

### 4.2 Durable Event Log

저장 대상 예시:

```text
session/started
user/message
agent/role-start
assistant/chunk
tool/call
tool/result
approval/request
approval/granted
context/usage
compaction/start
compaction/summary
compaction/end
agent/retry
agent/cancelled
session/completed
```

이 로그는 복구와 UI 관찰을 위한 완전한 실행 이력이다.

### 4.3 Model Surface

모델에게는 필요한 정보만 전달한다.

```text
system prompt
user messages
assistant messages
현재 유효한 tool call/result
compaction summary
최근 작업 상태
```

다음 정보는 Event Log에는 남기되 Model Surface에서는 제외한다.

- SSE chunk 단위 기록
- lifecycle 이벤트
- UI 전용 상태
- 오래된 approval 이벤트
- 이미 summary로 치환된 raw history
- telemetry

### 4.4 효과

- 서버 재시작 후 session resume 가능
- 모바일 재접속 후 현재 실행 상태 재구성 가능
- compaction을 해도 원본 기록 보존 가능
- debugging 가능성 증가
- 모델 context와 운영 로그를 독립적으로 관리 가능

---

## 5. Provider Error Recovery

모델 API 실패와 Agent 자체 실패를 분리한다.

현재 목표는 다음과 같다.

```text
LLM Request
   ↓
성공 → Agent Step 진행

실패
   ↓
Error Classifier
   ↓
Retry / Compact / Terminal
```

### 5.1 권장 정책

| 오류 | 처리 |
|---|---|
| HTTP 429 | backoff 후 retry |
| HTTP 500/502/503 | retry |
| network timeout | retry |
| connection reset | retry |
| context overflow | compact 후 retry |
| invalid request | terminal |
| invalid tool schema | terminal |
| 401/403 | terminal |

### 5.2 Backoff

예:

```text
1초
2초
4초
8초
```

상한과 최대 retry 횟수를 둔다.

모바일 UI에는 다음 상태를 전달한다.

```text
retrying
attempt
reason
next_delay
```

### 5.3 중요한 원칙

Provider failure는 가능하면 현재 turn을 복구하고 Agent 전체 session을 종료하지 않는다.

---

## 6. Followup / Steer / Inject Inbox

FORGE는 이미 실행 중 메시지 injection을 지원한다.

이를 명확한 의미를 가진 세 가지 동작으로 발전시킨다.

### Followup

현재 작업이 끝난 뒤 다음 turn에서 실행한다.

```text
현재 작업
↓
완료
↓
followup 메시지
```

### Steer

현재 작업을 취소하지 않고 다음 step부터 방향을 수정한다.

```text
현재 Tool 실행
↓
다음 LLM Step
+ 사용자 steering message
```

예:

> 테스트는 하지 말고 UI 수정만 진행해

### Interrupt

현재 실행을 취소하고 새로운 요청으로 전환한다.

```text
cancel current turn
↓
cleanup
↓
new turn
```

### 데이터 구조 예시

```python
class AgentInbox:
    followups: deque[Message]
    steering: deque[Message]
```

모든 inbox 변경은 durable event로 기록하는 것이 장기적으로 바람직하다.

---

## 7. Cooperative Cancellation

현재 session 단위 cancel flag 확인만으로는 긴 bash, HTTP streaming, Tool 실행을 즉시 멈추기 어렵다.

Cancellation은 실제 실행 계층까지 전달되어야 한다.

```text
User Cancel
   ↓
Agent Turn Cancellation Token
   ├─ LLM stream cancel
   ├─ bash subprocess terminate
   ├─ pending approval cancel
   ├─ pending question cancel
   └─ started tool cleanup
```

Python에서는 `asyncio.Task`, `asyncio.Event`, subprocess terminate/kill 등을 조합할 수 있다.

원칙:

- 시작되지 않은 Tool은 dispatch하지 않는다.
- 이미 시작된 Tool은 가능한 경우 cooperative하게 중단한다.
- 중단 결과를 session event에 기록한다.
- cancellation과 일반 failure를 구분한다.

권장 결과 코드:

```text
ABORTED_BEFORE_DISPATCH
ABORTED
TIMEOUT
FAILED
```

---

## 8. Tool Execution Pipeline

### 8.1 현재 위험

Tool 실행 관련 책임이 AgentRuntime에 계속 추가되면 `agent.py`가 다음 모든 책임을 갖게 된다.

- 승인
- args parsing
- 반복 호출 검사
- checkpoint
- 실행
- timeout
- cancellation
- diff
- telemetry
- state update
- 결과 정규화

이는 Agent Loop와 Tool 정책을 강하게 결합한다.

### 8.2 제안

Harness처럼 전체 Plugin Framework를 만들 필요는 없다.

다음 정도의 pipeline만 도입한다.

```text
validate
↓
authorize
↓
checkpoint
↓
dispatch
↓
normalize
↓
observe
```

예:

```python
result = await tool_executor.execute(
    name=name,
    arguments=args,
    workspace=workspace,
    cancellation=token,
)
```

AgentRuntime은 결과만 받아 다음 모델 step에 전달한다.

### 8.3 효과

- AgentRuntime 단순화
- Tool timeout 중앙 관리
- 승인 정책 중앙화
- 향후 MCP 연동 용이
- 테스트 가능성 향상

---

## 9. Parallel-safe Tool Execution

코드 탐색 Tool은 서로 독립적인 경우가 많다.

예:

```text
read_file A ─┐
read_file B ─┼→ parallel
read_file C ─┘
```

반면 mutation Tool은 exclusive하게 유지한다.

### Parallel-safe 후보

- read_file
- list_dir
- grep
- git status
- git log

### Exclusive 후보

- write_file
- edit_file
- bash mutation
- git checkout
- git commit

초기 concurrency limit은 4 정도로 시작하는 것을 권장한다.

병렬화를 위해 Agent Loop 전체를 재설계하지 말고 하나의 model response에 여러 parallel-safe tool call이 동시에 반환된 경우에만 적용한다.

---

## 10. Code Mode

Harness는 native function calling 외에 하나의 `run_code` transport 안에서 여러 도구를 SDK 형태로 호출하는 전략을 지원한다.

개념적으로 다음 차이가 있다.

### Native Tool Loop

```text
LLM
→ grep
→ LLM
→ read_file
→ LLM
→ read_file
→ LLM
```

### Code Mode

```text
LLM
→ run_code
    grep(...)
    read_file(...)
    read_file(...)
→ LLM
```

FORGE의 비용 효율성 철학과 잘 맞을 가능성이 있다.

다만 다음 위험이 있다.

- Sandbox 복잡도 증가
- Tool 권한 우회 가능성 검토 필요
- 실행 코드 디버깅 필요
- 사용자 승인 경계가 복잡해짐

따라서 Context/Recovery 계층이 안정된 이후 실험 기능으로 도입한다.

---

## 11. 도입하지 않을 것

DeepSeek Harness의 모든 구조를 복제하지 않는다.

현재 FORGE에서 피해야 할 것:

- Everything-is-a-plugin 구조
- 대규모 dependency injection framework
- 수십 개 package로 기능 분리
- 복잡한 capability seam 계층
- Cordis 스타일 전체 구조 복제
- 필요하지 않은 범용 SDK 추상화

FORGE의 강점은 다음이어야 한다.

```text
작고 이해 가능한 Python Runtime
+
강력한 DeepSeek Agent Loop
+
모바일 원격 제어
+
셀프호스팅
```

Harness의 운영 안정성 아이디어를 가져오되 Harness 자체가 되려고 해서는 안 된다.

---

## 12. 제안 구현 순서

### Phase A — Context Survival

1. Token meter 정리
2. Tool result pruner
3. Context pressure trigger
4. Summary compactor
5. Compaction checkpoint
6. context overflow → compact → retry

완료 조건:

> 장시간 반복 작업이 context 95%에서 종료되지 않고 자동 압축 후 계속 실행된다.

### Phase B — Durable Runtime

1. Session event schema 정의
2. append-only event persistence
3. Model Surface projection
4. 서버 재시작 후 session resume
5. 모바일 재접속 replay

완료 조건:

> 서버 프로세스를 재시작해도 이전 session의 작업 상태와 대화를 재구성할 수 있다.

### Phase C — Recovery

1. Provider error classifier
2. Retry/backoff
3. context overflow recovery
4. terminal/recoverable error 분리

완료 조건:

> 일시적인 DeepSeek API 장애가 Agent Session 종료로 이어지지 않는다.

### Phase D — Remote Steering

1. followup queue
2. steer queue
3. interrupt
4. durable inbox event

완료 조건:

> 모바일에서 실행 중인 장시간 작업을 중단하지 않고 방향 수정할 수 있다.

### Phase E — Tool Runtime

1. ToolExecutor 분리
2. timeout
3. cooperative cancellation
4. parallel-safe read tools

완료 조건:

> AgentRuntime에서 tool 정책 코드가 분리되고 탐색 작업이 병렬 실행될 수 있다.

### Phase F — Experimental Efficiency

1. Code Mode PoC
2. Native Tool Loop와 비용 비교
3. latency 비교
4. tool-call 정확도 비교

유의미한 효과가 있을 때만 정식 도입한다.

---

## 13. 측정 지표

기능을 추가하는 것보다 실제 개선 여부를 측정해야 한다.

최소 다음 telemetry를 기록한다.

### Agent

- session duration
- turn count
- step count
- reviewer cycle count
- recovery count

### Model

- prompt tokens
- completion tokens
- cached tokens
- request count
- retry count
- model별 비용

### Context

- 현재 context token
- context ratio
- pruning 횟수
- pruning으로 제거한 token
- compaction 횟수
- compaction 전/후 token

### Tool

- tool call count
- tool latency
- timeout count
- cancellation count
- parallel execution count

이를 기반으로 FORGE의 핵심 가설을 검증한다.

> 저렴한 모델을 반복 호출하는 구조가 고가 모델을 소수 호출하는 구조보다 실제 코딩 작업에서 비용 대비 성능이 좋은가?

---

## 14. 라이선스 및 코드 재사용 원칙

DeepSeek Harness의 구현을 참고할 때 다음 원칙을 지킨다.

- 설계 아이디어와 동작 원리는 FORGE 구조에 맞게 재구현하는 것을 기본으로 한다.
- 소스 코드를 직접 복사하는 경우 upstream 라이선스 조건과 저작권 고지를 확인하고 준수한다.
- FORGE에 불필요한 framework-specific 코드는 가져오지 않는다.
- upstream 변경에 FORGE가 종속되지 않도록 독립적인 내부 인터페이스를 유지한다.

---

## 15. 최종 방향

DeepSeek Harness에서 가장 가치 있는 부분은 Agent의 페르소나나 Planner/Coder 역할 분리가 아니다.

가져와야 할 핵심은 **오래 살아남는 Agent Runtime의 운영 기술**이다.

```text
FORGE Agent Intelligence

Planner
Coder
Reviewer
Debugger
       │
       ▼
─────────────────────────────
Agent Runtime Survival Layer
─────────────────────────────
Context Compaction
Durable Event Log
Recovery
Inbox / Steering
Cancellation
Tool Runtime
─────────────────────────────
       │
       ▼
DeepSeek API + Local Workspace
```

FORGE는 이 Survival Layer를 강화함으로써 단순한 코딩 챗봇이 아니라, 모바일에서 지시하고 장시간 맡겨둘 수 있는 실질적인 원격 코딩 에이전트로 발전한다.

첫 구현 우선순위는 다음과 같다.

> **Tool Result Pruning → Context Compaction → Context Overflow Recovery**

이 세 가지를 먼저 완성한 후 Event Log와 Remote Steering을 확장한다.
