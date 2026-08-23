# FORGE Priority Roadmap

## 최상위 원칙

FORGE의 경쟁력은 "싼 모델"이 아니다.

> **저렴한 모델을 강한 Harness로 통제해, 모델 단독 능력보다 높은 완료 신뢰성과 품질을 만드는 프로세스**가 핵심이다.

따라서 모든 변경은 다음 순서로 평가한다.

```text
1. success_rate / correctness
2. verified completion reliability
3. cost_per_success
4. elapsed
5. human intervention
```

Flash 사용률이나 token 감소는 보조 지표다. 품질이 떨어지면 최적화가 아니다.

# P0 — Verification / Completion Reliability

현재 Strict Verification Gate가 구현됐다. 다음은 의미를 엄밀하게 만든다.

- `PASSED / FAILED / UNAVAILABLE` 3상태
- test runner/config 오류를 PASS로 오판하지 않음
- failed/unavailable completion policy 명시
- verification 실패 시 commit/push 금지 invariant
- deterministic reliability regression test

# P1 — Durable Resume Safety

실제 Auto Resume은 구현됐다. 다음 단계는 재시작이 권한 확대로 이어지지 않게 하는 것이다.

- resume-safe approval/capability
- 기존 승인 범위와 새 위험 작업 구분
- resume 재충돌 loop guard 회귀 테스트
- restart 지점별 deterministic test

# P2 — Benchmark / Eval 확대

현재 R0 21-task deterministic harness를 현실적인 난이도로 확대한다.

- multi-file / integration / debugging / ambiguous task
- long-running/resume failure mode
- 동일 fixture로 model/harness 비교
- 외부 Claude Code/Codex 등과 비교 가능한 공통 checker

목표는 비용표가 아니라 **저가 모델 + Harness가 품질을 실제로 유지하는지 증명하는 것**이다.

# P3 — Bounded RSI R1

현재 promotion gate는 구현됐다.

다음:

```text
baseline
→ candidate worktree
→ 변경
→ 동일 benchmark
→ success/cost/elapsed gate
→ report
→ 사람 승인
```

자동 main merge는 당분간 하지 않는다.

# P4 — Scheduled / Condition / Deferred Jobs

예약 기반은 구현 중이다. 제품 기능 추가보다 durable semantics를 먼저 완성한다.

- restart
- idempotency
- timezone/DST
- duplicate execution 방지
- 실패/재시도 이력
- Web Push 운영 검증

# P5 — Tool Script / RPC

읽기/탐색 왕복을 묶어 model call을 줄인다. 단, success rate를 유지한다는 benchmark가 선행돼야 한다.

# P6 — Evaluation-Driven Model Routing

Flash-first/Pro escalation 정책을 고정 신념으로 두지 않는다. task class별 실제 성공률과 `cost_per_success`로 정책을 조정한다.

Harness가 품질을 보장하기 때문에 싼 모델을 적극 사용할 수 있지만, 필요한 곳에서는 강한 모델을 쓰는 것이 맞다.

# P7 — Skills Optimization

Curated/Learned/Project 3-tier 구조는 구현됐다.

다음은 Skill 수 증가가 아니라 효과 측정이다.

- selected skill별 성공률
- model/tool calls 변화
- 비용/elapsed 변화
- 반복적으로 무가치한 Skill 제거/병합

# P8 — ExecutionBackend / Security

- Local/Host/Docker 경계 정리
- 필요 시 SSHBackend
- workspace/path invariant
- Host Terminal/Screen/Camera authorization 지속 검증
- secret/audit 정책

# P9 — Productization

Tauri Desktop Host, 배포/업데이트, App/PWA 경험은 Agent 품질 기반이 안정된 뒤 고도화한다.

# 당분간 하지 않을 것

- 실측 근거 없는 Vector DB
- 역할 수를 늘리기 위한 Multi-Agent
- 거대한 plugin framework
- 자동 main merge RSI
- 모델 자체 fine-tuning
- Kubernetes/대규모 observability stack

# 장기 목표

```text
저렴한 모델
+ 최소한의 Agent 구조
+ 강한 Tool 실행
+ deterministic verification
+ durable recovery
+ benchmark-driven routing
+ bounded self-improvement
= 믿고 맡길 수 있는 autonomous development runtime
```

FORGE는 가장 싼 시스템을 목표로 하지 않는다.

**같은 비용에서 더 많은 '검증된 성공 작업'을 만들고, 더 저렴한 모델에서도 결과 품질을 유지할 수 있는 Harness**를 목표로 한다.
