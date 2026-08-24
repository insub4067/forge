# FORGE Roadmap Priority

> 2026-08-24 current source 기준. 이미 구현된 P0를 다시 계획하지 않는다.

## North Star

> **“이 변경 때문에 사용자가 내일부터 FORGE에 더 자주 실제 일을 맡기고, 확인·개입 부담이 줄어드는가?”**

기능 수, agent 수, provider 수는 KPI가 아니다.

## P0 — Daily-use Reliability / Dogfooding

현재 가장 가치 있는 일은 새로운 topology가 아니라 실사용에서 신뢰 결함을 잡는 것이다.

- gate semantic coverage: 요구사항을 충분히 대표하는지 external checker와 비교
- gate false-negative: 잘못된 gate가 맞는 코드를 막는 비율
- false completion / unverified completion 추적
- human intervention/ask_user/approval 빈도
- Project Memory saved/rejected 품질
- startup DB/schema/resume 오류가 broad exception에 묻히지 않게 가시성 강화
- 모바일에서 activity/task/final report가 중복·과잉 표시되지 않는지 계속 dogfood

성공 조건: 사용자가 “완료”를 다시 수동 검증하는 빈도와 작업 중 개입이 감소한다.

## P1 — Provider Independence

현재 main은 DeepSeek only다. 다음 확장점은 새 Agent가 아니라 provider boundary다.

최소 목표:

```text
AgentRuntime
→ Provider Adapter
   ├─ DeepSeek
   └─ OpenAI-compatible
```

내부 vLLM/SGLang 또는 다른 외부 provider를 같은 Harness에서 benchmark할 수 있게 한다. 과거 Ling/OpenRouter 실험의 실패를 무시하고 재도입하지 않는다.

승격 기준: verified success non-regression → cost_per_verified_task → elapsed.

## P2 — Persistent Execution / Automation

현재 Auto Resume와 Scheduled Jobs는 동작한다. 다음은 “정확히 언제/누가 run을 소유하는가”를 더 단단하게 만드는 단계다.

- Deferred/Condition watcher
- condition state/idempotency
- worker ownership/crash semantics
- independent worker/queue가 필요한 범위만 PoC
- scheduler/worker와 approval/budget 경계 통합

Temporal/Celery 같은 대형 workflow infra부터 넣지 않는다.

## P3 — Bounded Fresh Workers

Parallelism은 속도보다 **context isolation + verified throughput**을 위해서만 도입한다.

초기:

- read-only/research leaf
- self-contained task packet
- 2 workers 정도부터
- file ownership/isolated worktree 없이는 동시 mutation 금지
- final integration verification 필수

10-agent swarm은 비목표다.

## P4 — Tool / Execution Optimization

- Tool Script/RPC: 실제 round-trip bottleneck이 재현될 때 A/B
- ExecutionBackend(Local/Docker/SSH): remote target 요구가 생길 때 최소 interface
- Web search/fetch: local source로 해결할 수 없는 최신 문서 요구가 반복될 때 safe bounded tool

Architecture wishlist가 아니라 measured need로 시작한다.

## Deferred / Optional

- Tauri Desktop host
- WebRTC Screen/Camera
- full browser/computer-use
- home camera registry/condition detection
- large plugin ecosystem
- auto main merge
- speculative decoding/on-prem tuning(실제 내부 inference hardware가 생길 때)

## Already Done — 다시 계획하지 말 것

- verification 3-state
- Acceptance Gate Ledger + recovery + completion policy
- structured/persistent CompletionSummary
- failed/unverified commit/push policy
- resume-safe auto_approve/model_tier
- fresh Planner/Reviewer context
- large-file symbol tools/tool-result pruning
- compaction persistence
- evidence-bound Project Memory
- R0 25 tasks / R1 candidate worktree/no-op reject
- Scheduled one-shot/daily/interval foundations
- MCP stdio high-level task facade
- Mac Terminal/Screen/Input PoC
