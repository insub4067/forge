# FORGE Priority Roadmap

> 목적: FORGE가 기능 수를 늘리는 대신 실제 작업 완료 능력, 지속성, 비용 효율을 기준으로 현존 상위권 Coding Harness와의 격차를 줄이기 위한 우선순위를 정의한다.

## 최상위 원칙

FORGE의 최적화 목표는 `tokens/task`가 아니다.

> **동일하거나 더 높은 성공률을 유지하면서 더 적은 토큰, API 호출, 시간, 비용으로 작업을 완료한다.**

최우선 KPI는 **cost per successfully completed task**다.

새 기능은 다음 질문을 통과해야 한다.

1. 작업 성공률을 높이는가?
2. 인간 개입을 줄이는가?
3. 모델 호출 또는 토큰 비용을 줄이는가?
4. 장시간 작업의 복구 가능성을 높이는가?
5. 추가되는 복잡도가 얻는 효과보다 작은가?

아니라면 우선순위를 낮춘다.

---

# P0 — 실제 성능 측정과 Benchmark

가장 먼저 해야 한다.

현재 FORGE는 architecture와 기능은 빠르게 성장했지만 Claude Code, Codex 등과 비교할 수 있는 충분한 실증 데이터가 없다.

기능을 계속 추가하기 전에 반복 가능한 benchmark를 구축한다.

## 목표

동일한 repository/task를 대상으로 다음을 비교한다.

- FORGE + DeepSeek Flash/Pro
- Claude Code
- Codex
- 필요하면 다른 공개 coding harness

## 최소 측정값

- 성공/실패
- human intervention count
- elapsed time
- prompt/output tokens
- cache hit ratio
- model calls
- tool calls
- retries
- compactions
- Debugger activation
- Pro escalation
- estimated cost

핵심 파생 지표:

- success rate
- cost per successful task
- model calls per successful task
- review first-pass rate
- recovery success rate

## Benchmark 구성

최소 50개, 이후 100개 이상으로 확대한다.

- 단순 파일 수정
- 단일 버그 수정
- multi-file feature
- refactoring
- failing test debugging
- frontend/UI
- backend/API
- DB/schema
- repository exploration
- ambiguous requirement
- long-running task

실제 FORGE 자체 개발 이력을 benchmark task로 재사용한다.

## 완료 기준

FORGE 변경 전/후를 동일 task set으로 비교할 수 있어야 한다.

---

# P1 — Durable Worker / True Resume

현재 가장 큰 runtime 약점이다.

SSE/PWA 연결이 끊겨도 서버 작업은 유지할 수 있지만 FastAPI/worker 프로세스 자체가 죽으면 실행 중이던 작업을 실제 지점에서 resume하지 못한다.

## 목표 구조

```text
Client
  ↓
FastAPI Control Plane
  ↓
Durable Job
  ↓
Worker
  ↓
AgentRuntime
  ↓
Event / Checkpoint
```

UI lifecycle과 Agent execution lifecycle을 완전히 분리한다.

## 필요한 상태

- current role
- task state
- completed tool calls
- pending tool call
- context summary/checkpoint
- approval/question state
- retry/debugger count
- git checkpoint

## 복구

```text
Worker crash
→ restart
→ unfinished job 발견
→ last durable checkpoint load
→ 안전성 검증
→ execution resume
```

임의 지점에서 Python coroutine 자체를 복구하려 하지 않는다.

**명시적인 Agent state transition 경계에서 checkpoint**한다.

## 완료 기준

Agent 작업 중 backend/worker를 강제 종료하고 다시 실행해도 작업이 안전하게 이어진다.

---

# P2 — Parallel Worker / Coordinator

Durable Worker가 안정화된 뒤 진행한다.

최상위 agent system과의 큰 차이 중 하나다.

## 목표

독립 가능한 작업을 병렬 처리한다.

```text
Coordinator
├─ Backend Worker
├─ Frontend Worker
├─ Test Worker
└─ Research Worker
       ↓
   Result merge
       ↓
    Reviewer
```

## 원칙

모든 작업을 병렬화하지 않는다.

Coordinator가 dependency graph를 만들고 **독립적인 workstream만** 병렬화한다.

Worker에 main context 전체를 복사하지 않는다.

각 Worker는 self-contained task packet만 받는다.

이를 통해 병렬화 때문에 token 사용량이 폭증하는 것을 막는다.

## 완료 기준

병렬화 가능한 benchmark에서 sequential 대비 성공률을 유지하면서 elapsed time을 유의미하게 줄인다.

---

# P3 — Tool Script / RPC Mode

모델과 tool 사이의 불필요한 왕복을 줄이는 핵심 비용 최적화다.

현재:

```text
LLM
→ grep
→ LLM
→ read A
→ LLM
→ read B
→ LLM
→ git diff
→ LLM
```

목표:

```text
LLM
→ restricted tool script
   ├─ grep
   ├─ read A
   ├─ read B
   └─ git diff
→ aggregated result
→ LLM
```

## 우선 대상

- grep + read
- 여러 read_file
- git status + diff
- test result collection
- repository exploration

## 보안

host에서 임의 Python을 실행하는 구조로 만들지 않는다.

허용된 Tool RPC만 호출 가능한 제한된 executor를 사용한다.

Mutation tool은 기존 approval/security policy를 그대로 통과한다.

## 완료 기준

repository exploration benchmark에서 성공률 저하 없이 model round-trip과 token usage가 감소한다.

---

# P4 — Evaluation-Driven Model Routing

현재 Flash-first / Pro-on-demand 방향은 유지한다.

다만 heuristic이 아니라 benchmark 데이터로 정책을 개선한다.

## 측정 대상

- Planner Flash 실패율
- COMPLEX Planner Pro의 실제 개선율
- Reviewer 모델별 precision
- Debugger Flash → Pro escalation 효과
- thinking level별 비용/성공률

## 가능한 최적화

```text
Deterministic fast path
→ Flash
→ 실패 가능성 증가 시 Pro
```

하지만 routing 오판으로 재시도가 늘면 총비용이 오히려 증가한다.

항상 **최종 성공 작업당 비용**으로 판단한다.

자동 policy tuning은 충분한 데이터가 쌓인 뒤 검토한다.

---

# P5 — Scheduled / Condition Jobs

FORGE를 요청-응답형 coding agent에서 persistent development agent로 확장한다.

예:

```text
새벽
→ git fetch
→ tests
→ regression 확인
→ 문제 분석
→ 필요하면 수정
→ 사용자에게 결과 보고
```

또는:

```text
PR push
→ CI 감시
→ 실패
→ 로그 분석
→ 수정
→ push
→ 재검증
```

## Job 유형

- ScheduledJob
- ConditionJob
- DeferredJob

Durable Worker 위에서 구현한다.

Scheduler를 AgentRuntime 내부에 직접 섞지 않는다.

---

# P6 — ExecutionBackend

Agent의 reasoning과 실제 실행 위치를 분리한다.

```text
AgentRuntime
     ↓
ExecutionBackend
├─ Local
├─ Docker
└─ SSH
```

향후 DGX/원격 개발 서버/별도 sandbox machine을 자연스럽게 worker로 사용할 수 있는 기반이다.

우선순위:

1. 현재 Local/Host 실행 정리
2. DockerBackend
3. SSHBackend

실제 필요 전에는 cloud sandbox backend를 추가하지 않는다.

---

# P7 — Self-Improving Skills 고도화

현재 selective Skill과 save_skill 기반은 유지한다.

다음 단계는 Skill 개수를 늘리는 것이 아니라 **실제로 도움이 되는지 측정하는 것**이다.

측정:

- skill selected 여부
- skill별 성공률
- skill 사용 전/후 model calls
- skill 사용 전/후 Debugger activation
- skill 사용 전/후 비용

반복적으로 가치가 없는 Skill은 제거/병합한다.

Skill 수가 실제로 커져 I/O 병목이 확인될 때만 metadata index 또는 SQLite FTS5를 도입한다.

Vector DB는 현재 우선순위가 아니다.

---

# P8 — Security Hardening

FORGE는 shell/file/Git 권한을 가진 agent이므로 일반 웹앱보다 공격 영향도가 크다.

이미 기본 Docker sandbox와 approval gate를 유지하면서 다음을 강화한다.

- workspace boundary invariant
- path traversal tests
- command policy tests
- secret redaction
- API key secure storage
- audit event integrity
- host mode 명확한 위험 경고
- remote access authentication documentation

Public Internet에 직접 노출하는 사용법은 지원하지 않는다.

Cloudflare Tunnel 사용 시에도 Tunnel 자체가 authorization이 아니므로 Cloudflare Zero Trust/Access 또는 동등한 접근 통제를 권장한다.

---

# P9 — Tauri Desktop Host

제품성과 배포 경험 개선에는 가치가 높지만 Agent 성능 자체보다 우선하지 않는다.

기존 proposal의 원칙을 유지한다.

```text
Tauri = Desktop Host
FastAPI = Control Plane
AgentRuntime = Harness
Vue = UI
```

Tauri 때문에 AgentRuntime을 Rust로 재작성하거나 PWA를 제거하지 않는다.

먼저 sidecar PoC로 검증한다.

---

# 당분간 하지 않을 것

다음은 현재 핵심 병목이 아니다.

- Vector DB
- 거대한 plugin ecosystem
- 다수 messenger adapter
- 범용 personal assistant 기능
- 모든 cloud sandbox 지원
- AgentRuntime Rust 전면 재작성
- Kubernetes
- Prometheus/Grafana 등 대규모 observability stack
- 복잡한 graph framework 도입
- 모델 자체 fine-tuning
- 기능 수를 늘리기 위한 subagent 남발

실제 benchmark에서 필요성이 증명되면 다시 평가한다.

---

# 권장 실행 순서

```text
P0 Benchmark / Eval
       ↓
P1 Durable Worker
       ↓
P2 Parallel Coordinator
       ↓
P3 Tool Script/RPC
       ↓
P4 Data-driven Model Routing
       ↓
P5 Scheduled/Condition Jobs
       ↓
P6 ExecutionBackend
       ↓
P7 Skills Optimization
       ↓
P8 Security Hardening
       ↓
P9 Tauri Productization
```

P0는 한 번 끝내는 Phase가 아니다.

모든 단계에서 benchmark를 다시 실행한다.

```text
Implement
→ Benchmark
→ Compare
→ Keep / Revert
→ Next
```

성능 개선이 확인되지 않는 복잡한 변경은 제거한다.

---

# 장기 목표

FORGE가 목표로 해야 할 것은 단순히 Claude Code/Codex 기능 목록을 복제하는 것이 아니다.

목표는:

> **저렴한 모델을 강한 Harness로 조직하여, 실제 소프트웨어 작업을 높은 성공률과 낮은 성공 작업당 비용으로 장시간 자율 수행하는 self-hosted coding agent platform**

이다.

최종적으로 다음 특성을 가져야 한다.

- 장시간 살아남는다.
- 실패 후 스스로 복구한다.
- 독립 작업을 병렬 처리한다.
- 필요한 경우에만 비싼 모델을 사용한다.
- 성공 경험을 Skill로 재사용한다.
- 모델/tool 왕복을 최소화한다.
- Desktop과 Mobile 어디서든 동일 runtime을 제어한다.
- 모든 최적화를 benchmark 데이터로 판단한다.

FORGE의 경쟁력은 가장 큰 모델을 소유하는 데 있지 않다.

**같은 모델 자원으로 더 많은 실제 작업을 끝내는 Harness를 만드는 것**이 핵심이다.
