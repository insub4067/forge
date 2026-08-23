# FORGE — 기능 목록

> 기준: 2026-08-23 `main`

## Agent / Quality Harness

| 기능 | 상태 |
|---|---|
| Triage → Chat / Developer | ✅ |
| 올인원 Developer | ✅ |
| Flash-first / Pro escalation | ✅ |
| Strict test/build Verification Gate | ✅ |
| verification 실패 bounded repair | ✅ |
| 모델의 done과 process completed 분리 | ✅ |
| verification PASSED/FAILED/UNAVAILABLE 3상태 | ✅ |
| repeated tool / concurrent-run guard | ✅ |
| runtime steering / cancel | ✅ |

## Persistence / Recovery

| 기능 | 상태 |
|---|---|
| PostgreSQL session/message/task/agent-run | ✅ |
| step-level history persistence | ✅ |
| JSONL event log | ✅ |
| event polling + seq dedup | ✅ |
| 서버 재시작 후 Durable Auto Resume | ✅ |
| resume crash-loop guard | ✅ |
| resume-safe approval/capability | ✅ |

## Context / Skills / 비용

- context pruning / compaction / cache telemetry ✅
- reasoning provider recovery ✅
- Curated / Learned / Project 3-tier Skills ✅
- selective Skill injection ✅
- model별 token/cost telemetry ✅
- Tool Script/RPC ⬜

> 비용 최적화는 success-rate gate 아래에서만 수행한다. 저렴한 모델 사용 자체가 제품 목표가 아니다.

## Verification / Git

- npm build / pytest 자동 검증 ✅
- 검증 실패 시 repair/reverify ✅
- verified completion 경로 auto commit/push ✅
- failed verification에서 commit/push 차단 ✅ (회귀 테스트 지속 필요)
- Git panel ahead/behind + push/pull ✅

## Benchmark / RSI

- deterministic R0 benchmark harness ✅
- 21 task fixture/checker suite ✅
- benchmark quality self-test ✅
- model tier 비교 ✅
- promotion gate(success → cost → elapsed) ✅
- candidate worktree 자동 실행 ⬜
- 자동 merge ⬜ (의도적으로 사람 승인 유지)

## Remote / PWA

- 세션 / 예약 / 맥 정보구조 ✅
- status/event reconnect 복구 ✅
- Git / Files / Skills / Metrics / Kanban / Vision ✅
- Mac host PTY Terminal ✅
- view-only Screen ✅
- Camera JPEG polling PoC ✅
- `FORGE_AUTH_TOKEN` HTTP/WebSocket auth ✅
- Zero Trust/VPN 병행 권장 ✅

## Automation

- Scheduled Job 기반 🟡
- workspace fallback ✅
- Deferred / Condition semantics 🟡
- restart/idempotency/timezone 검증 🟡
- Web Push 구현 경로 존재(운영 검증 지속)

## 다음 우선순위

1. benchmark 확대
2. bounded RSI candidate pipeline
3. Scheduler durable semantics
4. Tool Script/RPC
5. ExecutionBackend
