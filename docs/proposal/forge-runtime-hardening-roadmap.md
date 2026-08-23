# FORGE Runtime Hardening Roadmap

> 상태: Proposal / Priority Roadmap
> 작성 기준: 2026-08-23
> 목표: **FORGE를 범용 Agent Framework가 아니라, 검증 가능한 저비용 Autonomous Software Execution Runtime으로 강화한다.**

## 1. 제안 배경

FORGE는 현재 다음 강점을 이미 갖고 있다.

- 올인원 Developer 실행 루프
- Flash-first / stronger-model escalation
- 실제 build/test를 사용하는 Strict Verification Gate
- bounded repair
- Durable Auto Resume
- PostgreSQL + JSONL event logging
- deterministic R0 benchmark와 promotion gate
- 모바일 PWA 기반 원격 제어
- Docker/Host 실행
- MCP 기반 외부 위임

외부 시스템과 비교하면 DeepSeek Harness는 plugin/capability/event architecture가 더 일반화되어 있고, Orca는 worktree 기반 병렬 Agent orchestration이 강하다. 그러나 FORGE가 이들을 그대로 복제하면 제품 정체성이 흐려지고 구조·비용이 증가한다.

따라서 이 제안은 다음 원칙을 따른다.

> **좋은 아키텍처 아이디어만 흡수하고, FORGE의 핵심인 verified completion + low cost + remote execution을 더 강하게 만든다.**

---

## 2. 제품 포지션

FORGE가 지향할 위치는 다음과 같다.

```text
DeepSeek Harness
= 범용 / 플러그인 가능한 Agent Harness Framework

Orca
= Multi-Agent Fleet / ADE

FORGE
= Verified Autonomous Software Execution Runtime
```

FORGE의 목표는 가장 많은 Agent를 지원하는 것이 아니다.

```text
Cheap / appropriate model
        ↓
bounded autonomous execution
        ↓
real code/tool actions
        ↓
deterministic verification
        ↓
repair / resume / escalation
        ↓
verified completion
```

북극성은 계속 다음 순서를 유지한다.

```text
success_rate / correctness
→ verified completion
→ cost_per_success
→ elapsed
→ human intervention
```

---

# 3. P0 — Verification Gate 3-State

현재 FORGE의 가장 중요한 차별점은 모델의 "완료" 발화를 신뢰하지 않고 실제 build/test 결과가 completion을 결정한다는 점이다.

이 invariant를 더 강하게 만든다.

## 목표 상태

```text
Developer says done
      ↓
Verification Gate
 ├─ PASSED
 │    → verified completion
 │    → commit/push eligible
 │
 ├─ FAILED
 │    → bounded repair
 │    → verification again
 │
 └─ UNAVAILABLE
      → verified completion 금지
      → 명시적 상태/사유 기록
```

## 필수 원칙

- `PASSED`: 실제 검증 명령이 실행되고 성공한 경우만 허용
- `FAILED`: 검증 명령이 정상 실행됐으나 실패
- `UNAVAILABLE`: 테스트/빌드 환경 부재, 설정 오류, dependency/tool 부재 등으로 검증 자체를 수행할 수 없음
- `UNAVAILABLE`을 성공으로 취급하지 않는다.
- 자동 commit/push는 `PASSED`에서만 가능하도록 invariant를 강제한다.

## 기대 효과

FORGE의 품질 보증을 모델 품질과 분리한다.

> **Model intelligence는 가변이지만 completion contract는 고정한다.**

---

# 4. P1 — ExecutionBackend Capability Seam

현재 Docker/Host 실행을 하나의 명확한 execution contract 아래로 묶는다.

목표:

```text
Developer / Tool Layer
        ↓
ExecutionBackend
 ├─ DockerBackend
 ├─ LocalBackend
 ├─ SSHBackend
 └─ future RemoteWorkerBackend
```

개념적 인터페이스:

```python
class ExecutionBackend:
    async def read_file(...): ...
    async def write_file(...): ...
    async def exec(...): ...
    async def terminal(...): ...
    async def workspace(...): ...
```

## 설계 원칙

- Agent loop가 backend 종류를 알지 않게 한다.
- filesystem / subprocess / terminal / workspace가 같은 execution world를 공유하도록 한다.
- permission/approval 정책은 backend 변경으로 우회되지 않아야 한다.
- Host는 명시적 high-trust backend로 유지한다.
- SSH/remote 지원을 추가해도 Developer 코드를 분기시키지 않는다.

## 기대 효과

- Mac / Linux / 원격 서버 / 향후 DGX 등의 실행 위치 교체 가능
- sandbox 정책 일관성 향상
- 테스트 가능성 향상
- backend-specific branching 감소

---

# 5. P2 — Authoritative Event + Checkpoint Replay

현재 PostgreSQL, step history, JSONL, SSE를 활용하되 runtime transition을 더 명확한 event contract로 승격한다.

예시:

```text
TaskCreated
ModelSelected
RunStarted
StepStarted
ToolCalled
ToolResultRecorded
PatchCreated
VerificationStarted
VerificationPassed
VerificationFailed
VerificationUnavailable
RepairStarted
ModelEscalated
ApprovalRequested
ApprovalResolved
CheckpointSaved
RunResumed
Completed
Failed
Cancelled
```

## 핵심 원칙

> **Model-visible or state-critical means reconstructable.**

모델이 본 중요한 입력과 runtime의 중요한 상태 변경은 persistence에서 재구성 가능해야 한다.

## Resume

```text
process crash / restart
        ↓
load persisted run state
        ↓
replay authoritative events
        ↓
restore checkpoint + capabilities
        ↓
continue from safe boundary
```

Python coroutine 자체를 복원하는 것이 아니라, 저장된 execution state를 기반으로 안전한 step boundary에서 재구성한다.

## 반드시 지킬 것

- resume 시 approval 권한 확대 금지
- 동일 tool side effect의 중복 실행 방지
- idempotency key / event sequence 사용
- crash-loop guard 유지

---

# 6. P3 — Benchmark-Driven Multi-Model Router

모델 선택을 단순 heuristic이 아니라 FORGE의 실제 benchmark telemetry 기반으로 발전시킨다.

Agent는 계속 하나의 Developer다.

```text
Developer
 ├─ low-cost model A
 ├─ low-cost model B
 ├─ DeepSeek Flash
 ├─ stronger candidate
 └─ DeepSeek Pro
```

새 모델마다 별도 Agent class를 만들지 않는다.

## Routing 판단 데이터

task class별로 다음을 축적한다.

```text
success_rate
verified_completion_rate
cost_per_success
tokens_per_success
calls_per_success
elapsed_p50 / p95
repair_count
escalation_rate
cache_hit_rate
```

예:

```text
frontend_fix:
  model A → success 94%, CPS $0.0005
  model B → success 88%, CPS $0.0002
  model C → success 97%, CPS $0.0015
```

정책은 단순 가격이 아니라 success gate를 먼저 적용한다.

## 기본 전략

```text
cheap capable model
      ↓
verify
 ├─ PASS → stop
 └─ FAIL → repair
              ↓ repeated/stuck
          stronger candidate
```

무료 preview 모델은 가격이 0이더라도 raw efficiency와 privacy/rate-limit 리스크를 별도로 기록한다.

---

# 7. P4 — Task Worktree Isolation

동시에 여러 세션을 실행해도 같은 working tree를 직접 공유하지 않도록 optional task worktree를 지원한다.

```text
Repository
 ├─ .forge/worktrees/task-a
 ├─ .forge/worktrees/task-b
 └─ .forge/worktrees/task-c
```

## 목적

- 동시 실행 파일 충돌 방지
- candidate benchmark 격리
- rollback 단순화
- parallel execution 기반 확보

## lifecycle

```text
TaskCreated
 → create worktree
 → Developer execution
 → verification
 → result/diff
 → human or policy approval
 → merge/cherry-pick
 → cleanup
```

기본 단일 작업에는 현재 workspace mode를 유지할 수 있고, 동시/실험 작업에서만 worktree를 활성화해도 된다.

---

# 8. P5 — RSI R1: Candidate → Benchmark → Human Promotion

현재 R0 deterministic benchmark와 promotion gate를 실제 isolated candidate workflow로 확장한다.

```text
Baseline
    ↓
Candidate generated
    ↓
Candidate worktree
    ↓
R0 benchmark
    ↓
compare:
 success_rate
 → CPS
 → elapsed
    ↓
PASS
    ↓
Human approval
    ↓
promote / merge
```

## 안전 원칙

- 자기 수정 자동 merge 금지
- baseline보다 success rate가 낮으면 즉시 reject
- benchmark fixture 오염 방지
- rollback 가능한 commit/worktree 단위 유지
- promotion에는 사람 승인 유지

이 단계까지 구현되면 FORGE의 RSI는 "스스로 코드를 바꾸는 기능"이 아니라 **측정 가능한 bounded harness improvement loop**가 된다.

---

# 9. P6 — Optional Parallel Developers

멀티에이전트는 기본 구조가 아니라 어려운 문제를 위한 선택적 search strategy로만 도입한다.

금지 구조:

```text
Planner → Coder → Reviewer → Debugger
```

권장 구조:

```text
Hard Task
   ↓
Budget Gate
   ↓
 ┌───────────────┬───────────────┐
 │               │               │
Developer A   Developer B    Developer C
model A       model B        model C
worktree A    worktree B     worktree C
 │               │               │
 └───────────────┴───────────────┘
                 ↓
       deterministic verification
                 ↓
      best verified candidate
```

## 기본 정책

```text
normal task  → 1 Developer
hard task    → optional 2 candidates
extreme task → optional 3 candidates
```

parallelism은 성공률 향상이 추가 비용보다 큰 경우에만 benchmark로 승격한다.

즉 Multi-Agent 자체가 기능 목표가 아니다.

> **Parallel execution은 어려운 문제에서 search budget을 늘리는 옵션이다.**

---

# 10. P7 — Visual Verification Loop

Vision을 별도 조직처럼 확장하지 말고 Developer capability로 통합 가능한 방향을 유지한다.

장기 목표:

```text
See
 ↓
Inspect Code
 ↓
Edit
 ↓
Build / Run
 ↓
Capture
 ↓
Compare
 ↓
Repair if needed
```

즉:

> **See → Code → Run → See → Repair**

현재 Screen / frontend build / vision 기능을 재사용하고 visual repair cycle에는 명확한 bound를 둔다.

---

# 11. 보안 강화 원칙

기능 확장보다 capability boundary가 우선이다.

특히 다음을 invariant로 관리한다.

- approval은 session/task scoped
- resume가 approval을 자동 확대하지 않음
- Host backend는 명시적 opt-in
- Terminal/Screen/Camera는 별도 high-risk capability
- MCP / REST / PWA가 동일 policy gateway를 통과
- 외부 무료/stealth provider에는 민감 workspace를 보내지 않도록 provider policy 적용 가능하게 설계
- commit/push는 verified completion 경로에서만 자동화

---

# 12. 구현 우선순위

```text
P0  Verification PASSED / FAILED / UNAVAILABLE
 ↓
P1  ExecutionBackend seam (Local / Docker / SSH)
 ↓
P2  Authoritative Event + Checkpoint Replay
 ↓
P3  Benchmark-driven Multi-Model Router
 ↓
P4  Task Worktree Isolation
 ↓
P5  RSI candidate → benchmark → human promotion
 ↓
P6  Optional Parallel Developers
 ↓
P7  Visual See → Code → Run → See loop
```

## 우선순위 이유

1. 품질 contract를 먼저 고정한다.
2. 실행 환경 abstraction을 정리한다.
3. durable state를 안정화한다.
4. 그 위에서 모델 비용 최적화를 한다.
5. worktree로 격리 기반을 만든다.
6. RSI와 병렬 execution을 안전하게 올린다.
7. visual loop는 기존 기반을 활용해 마지막에 확장한다.

---

# 13. 하지 말아야 할 것

이번 방향에서 명시적으로 피한다.

- Cordis/LangGraph/CrewAI 스타일 전체 rewrite
- "Everything is a Plugin"을 목표로 한 과도한 추상화
- Planner / Reviewer / Debugger 기본 파이프라인 복구
- 모델별 Agent class 생성
- Multi-Agent를 기본 실행 경로로 사용
- benchmark 없는 model routing
- 검증되지 않은 자동 self-modification merge
- mobile/remote 제품성을 버리고 CLI harness로 회귀

FORGE는 범용 Agent OS가 될 필요가 없다.

---

# 14. 완료 정의

이 로드맵의 성공은 기능 수로 판단하지 않는다.

FORGE가 다음 문장을 실제로 보장할 수 있어야 한다.

> **어떤 지원 모델이든 적절한 격리 환경에서 실행하고, 실제 소프트웨어 결과를 검증하며, 실패하면 제한적으로 수리·승격·복구하고, 재시작 후에도 이어가며, 성공 작업당 비용까지 측정할 수 있다.**

최종적으로 FORGE의 경쟁력은 특정 모델이 아니다.

```text
Model commodity
     ↓
FORGE Harness
     ↓
Reliable execution
     ↓
Verified result
```

모델이 바뀌어도 Harness의 품질 contract와 측정 시스템이 남는 구조를 목표로 한다.
