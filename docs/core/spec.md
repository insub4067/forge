# FORGE — 요구사항 정의서

> 기준: 2026-08-23 `main`

## 1. 제품 목표

FORGE는 특정 LLM에 종속된 챗봇이 아니라 LLM을 판단 엔진으로 사용하는 실행 Runtime이다.

핵심 가치는 **싼 모델 자체가 아니라, 저렴한 모델로도 결과 품질을 보장하는 Harness 프로세스**다.

> 모델의 자기확신을 신뢰하지 않고, 실행·검증·수리·재검증을 프로세스로 강제해 실제 작업 성공률을 확보한다.

최적화 우선순위:

1. success rate / 결과 품질 유지·향상
2. deterministic verification을 통과한 완료
3. cost per successfully completed task 감소
4. elapsed 감소
5. human intervention 감소

비용 감소로 성공률이 떨어지면 regression이다.

## 2. 실행 모델

```text
Goal → Triage → [Chat | Developer]
                    ↓
             Plan → Execute → Self-verify/Repair
                    ↓
             Strict Verification Gate
               ├─ PASS → completed
               └─ FAIL → bounded repair → verification_failed
```

Developer는 Flash+thinking을 기본으로 하고 막힐 때만 Pro로 승격한다. 별도 Planner/Reviewer/Debugger를 기본 파이프라인에 두지 않는다.

## 3. 현재 구현 범위

- DeepSeek/OpenRouter provider와 Flash/Pro/Vision routing
- read/list/grep/write/edit/bash/ask_user/update_tasks/save_skill/build_frontend
- approval, cancel, runtime injection
- Docker Sandbox + Host opt-in
- PostgreSQL session/message/task/agent-run persistence
- step-level history persistence
- JSONL event log / event polling / status recovery
- **Durable Auto Resume** + crash-loop guard + `AUTO_RESUME=0`
- Strict Verification Gate + bounded repair
- verified completion 경로의 auto commit/push
- context pruning / compaction / cache telemetry
- Curated/Learned/Project 3-tier Skills
- HTTP/WebSocket application auth(`FORGE_AUTH_TOKEN`)
- deterministic R0 benchmark(21 tasks)와 benchmark quality test
- bounded RSI promotion gate(R1 판정부)
- 모바일 PWA / Git / Files / Skills / Metrics / Kanban / Vision
- Mac Terminal / Screen / Camera PoC
- Scheduled Job 기반

## 4. 품질 보증 정책

`completed`는 모델의 문장이 아니라 프로세스가 결정한다.

- 감지된 build/test를 실제 실행한다.
- 실패 시 제한된 횟수만 repair한다.
- 검증 실패 상태에서 commit/push하지 않는다.
- 검증 결과를 `PASSED / FAILED / UNAVAILABLE`로 분리한다(실행 불가·설정 오류·timeout은 UNAVAILABLE).
- 테스트를 실행할 수 없었다는 사실을 테스트 성공으로 기록하지 않는다.

## 5. Model Policy

| 역할 | 정책 |
|---|---|
| Triage | Flash, 경량 분류 |
| Chat | Flash, non-thinking |
| Developer | Flash + thinking 기본, 막힘 시 Pro 승격 |
| Vision | Vision model, 필요할 때만 |

강한 모델을 기본으로 쓰지 않는 이유는 비용 자체가 아니라 **Harness가 검증을 담당하기 때문에 가능한 모델 효율화**다. 모델 정책 변경은 benchmark 성공률을 먼저 통과해야 한다.

## 6. Context / Skills

- provider prompt token 기준 pressure
- 75% compaction / 95% hard block 정책
- 긴 tool result model-free pruning
- stable prefix/cache telemetry
- Curated → Learned(`~/.forge/skills`) → Project(`<workspace>/.forge/skills`) 3계층
- 충돌 시 Project가 높은 authority
- 관련 Skill만 선택적으로 주입

## 7. Reliability

- provider retry/recovery
- repeated tool guard
- concurrent run guard
- bounded escalation/repair
- step-level persistence
- 서버 재시작 시 unfinished run 자동 재개
- resume 중 재충돌에 대한 loop guard
- SSE 단절 시 status/event polling 복구

resume 시 권한이 재시작 전보다 확대되지 않도록 approval/capability 경계를 강화했다: 재시작 전 auto_approve 값을 그대로 복원(True 강제 없음), 세션별 승인 필터, BLOCKED_COMMANDS 차단.

## 8. Evaluation / RSI

R0 benchmark는 fixture → Agent → deterministic checker로 동작하며 LLM-as-a-judge를 사용하지 않는다.

승격 판단은 사전식이다.

```text
success_rate 후퇴 → reject
success 유지 → cost_per_success 비교
비용 동률 → elapsed 비교
동률 → 변경할 이유가 없으므로 reject
```

`backend/rsi.py`에는 promotion gate가 구현돼 있지만 candidate worktree 실행/merge는 아직 자동화하지 않는다. 최종 승인은 사람에게 둔다.

## 9. Remote / Automation

PWA는 IDE 복제가 아니라 Agent 지휘·복구 인터페이스다.

- 세션 / 예약 / 맥
- Terminal / Screen / Camera
- Git / Files / Skills / Metrics
- Scheduled Job 기반

Condition/Deferred Job, timezone/idempotency/restart semantics는 계속 고도화한다.

## 10. 보안

- `FORGE_AUTH_TOKEN`으로 HTTP/WebSocket 보호
- mutation approval
- workspace boundary
- Docker 기본, Host 명시적 opt-in
- Zero Trust/VPN은 application auth를 대체하지 않음
- Host Terminal은 원격 shell과 동일한 위험도로 취급

## 11. 다음 우선순위

1. benchmark 확대 및 실제 비교 데이터 축적
2. bounded RSI candidate worktree/promotion pipeline
3. Scheduler durable semantics
4. Tool Script/RPC
5. ExecutionBackend

Vector DB, 무분별한 Multi-Agent, 거대한 plugin framework는 실측 병목이 생기기 전 기본 해법으로 사용하지 않는다.
