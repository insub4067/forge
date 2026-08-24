# FORGE — 작업 진행 상태

> 마지막 갱신: 2026-08-24 `main`

## 현재 요약

FORGE는 **저렴한 모델을 강한 Harness 안에서 실행해 품질을 프로세스로 보증하는 self-hosted coding runtime**으로 수렴하고 있다.

핵심 KPI는 단순 token 절감이 아니다.

```text
성공률/품질 유지·향상
→ 검증된 완료
→ cost per successful task 감소
→ elapsed 감소
→ human intervention 감소
```

## 완료된 핵심 기반

- [x] Triage → Chat / 올인원 Developer
- [x] Flash-first, 필요 시 Pro escalation
- [x] Strict Verification Gate(test/build 실제 실행)
- [x] verification 실패 시 bounded repair
- [x] 검증 완료 경로의 auto commit/push
- [x] step-level history persistence
- [x] 서버 재시작 후 Durable Auto Resume
- [x] resume crash-loop guard / `AUTO_RESUME=0`
- [x] JSONL event log + event polling/seq dedup
- [x] PostgreSQL persistence / model별 telemetry
- [x] Curated / Learned / Project 3-tier Skills
- [x] `FORGE_AUTH_TOKEN` HTTP/WebSocket 보호
- [x] deterministic R0 benchmark 21 tasks + quality tests
- [x] bounded RSI promotion gate
- [x] Mac Terminal / Screen / Camera PoC
- [x] 예약 작업 기반 (one-shot/daily/interval, timezone, restart 복원)
- [x] 예약 작업 durability (DST 안전 daily, retry 정책, 원자적 claim 중복 방지)

## 품질 보증 상태

가장 중요한 변화는 모델의 "done"과 실제 완료를 분리한 것이다.

```text
Developer done
→ testing
→ process가 test/build 실행
→ PASS만 completed
```

(2026-08-24 해결) pytest exit code 처리는 `PASSED / FAILED / UNAVAILABLE` 3상태로 분리됐다.
exit 2/3/4/5와 timeout은 `unavailable`로 남아 "검증 못 함"이 "검증 성공"으로 승격되지 않는다.

### Gate Coverage Completion Policy (2026-08-24)

> **Gate가 없는 코드 변경은 완전히 검증된 완료로 취급하지 않는다.**

실측(격리 프로브 3/3)에서 모델은 `update_tasks`는 부르고 `update_gates`만 건너뛰었고,
그 run들이 전부 `completed`로 끝났다. gate가 없으면 완료 근거는 generic verification
(기존 test/build 통과) 하나뿐이고, 사용자 요구사항 충족은 확인되지 않는다.

현재 정책:

```text
Developer 구현
→ files_changed > 0 ?
   → gate 0 ?  → Gate Recovery 1회(gate 등록 전용 턴, flash, step 3)
                 → 여전히 gate 0 → generic verification → completed_unverified
   → gate > 0  → 기존 검증 흐름(generic → acceptance → integration)
```

- gate 없음 ≠ `verification_failed` (실패한 게 아니다)
- gate 없음 ≠ `completed` (완전히 검증된 것도 아니다)
- gate 없음 = `completed_unverified`
- 부수 결과: gate 없는 run은 **origin push 대상이 아니다**(검증된 것만 배포 경로).
- 복구는 **최대 1회**. 복구가 예외로 죽어도 run은 안전 상태로 마감한다.
- 코드 변경이 없거나 작업 run이 아니면 복구하지 않는다(억지 gate 금지).

**알려진 리스크(관찰 중, 미완화)**: 복구가 만든 gate가 잘못 작성돼 non-zero로 끝나면
(예: 존재하지 않는 경로로 `cd`, import 오타) 프로세스는 그걸 코드 결함으로 보고 Developer
수리 루프를 태운다 → 맞는 코드가 `verification_failed`로 갈 수 있다. 잘못된 코드를 push하지는
않으므로 invariant는 유지되고, false-negative("못했습니다")는 허용 범위다. 프롬프트를 cwd
가정 없이 쓰도록 강화했고(프로브에서 4건 중 3건 정상), 발화 여부는 telemetry로 관찰한다 —
`coverage=recovered_gated` 중 `verification_failed` 비율이 뜨면 그때 겨냥한다(추측 완화 금지).

핵심 함수: `resolve_completion_verification`, `needs_gate_recovery`,
`build_gate_recovery_context`, `_coverage_kind` (전부 순수 함수 + 테스트로 고정).
계측: `gate_coverage` 이벤트(`coverage` ∈ gated / recovered_gated / generic_only /
no_change / not_applicable), 집계는 `backend/gate_coverage.py`.

## 핵심 KPI

기능 수나 token 절감이 아니다. 아래 순서로 본다.

| 지표 | 의미 |
|---|---|
| `verified_task_success_rate` | 검증까지 통과한 완료 비율 |
| **`false_completion_rate`** | **"완료했습니다" 했지만 요구사항 미충족 — 가장 위험한 실패** |
| `human_interventions_per_task` | 사람이 끼어들어야 한 횟수 |
| `repair_success_rate` | 검증 실패 후 수리가 성공한 비율 |
| `cost_per_verified_task` | 검증된 완료 1건당 비용 |
| `elapsed_per_verified_task` | 검증된 완료 1건당 소요 시간 |

일반 실패("못했습니다")는 허용 가능하다. false completion은 아니다 — 사용자가 확인하지
않아도 되는 에이전트라는 전제 자체를 깨기 때문이다. Gate coverage는 이 지표를 줄이는 수단이다.

## Durable Resume

이전 문서의 "진짜 resume 미구현" 상태는 더 이상 맞지 않는다. 현재는 unfinished run을 startup에서 찾아 저장된 history 기반으로 headless resume한다.

다만 resume 시 approval을 자동 처리하는 경로가 원래 run보다 권한을 넓힐 가능성이 있으므로 **resume-safe capability/approval**이 다음 보안 과제다.

## Benchmark / RSI

- R0 deterministic benchmark: 21 tasks
- checker 자체 false-positive/정답 판정 self-test
- model tier 비교 기반
- `backend/rsi.py`: success rate → cost → elapsed promotion gate

아직 자동화되지 않은 것:

- candidate worktree 생성/실행
- baseline/candidate 자동 benchmark orchestration
- promotion 후 merge

최종 merge는 당분간 사람 승인으로 유지한다.

## Remote Mac

- Host PTY + WebSocket + xterm.js Terminal
- view-only Screen
- `imagesnap` Camera polling PoC
- application auth 추가됨

Host capability는 여전히 높은 위험 영역이므로 network Zero Trust와 application auth를 둘 다 유지한다.

## Persistent Automation

Scheduled Job 기반은 구현됐지만 Condition/Deferred, restart/idempotency/timezone/DST semantics는 추가 검증이 필요하다.

## 다음 우선순위

### P0 — Reliability semantics
- [x] verification `PASSED / FAILED / UNAVAILABLE` (`_verify` 3상태)
- [x] failed/unavailable에서 commit/push invariant 테스트 (`test_acceptance_gates`,
      `test_reliability_invariants` — verification_failed는 커밋 금지, completed_unverified는 push 금지)
- [x] resume-safe approval/capability (재개가 저장된 auto_approve·model_tier를 복원, 권한 확대 없음)
- [ ] **acceptance gate 커버리지 강제** — 계측(G0)·정직 표기(G1) 완료, 강제(G2)는 실사용 데이터 대기.
      현 최우선 신뢰성 과제 → `docs/proposal/gate-coverage-enforcement.md`

### P1 — Evaluation
- [ ] benchmark task/난이도 확대
- [ ] 외부 harness와 동일 task 비교
- [ ] model/skills 정책을 success-rate gate로 평가

### P2 — Bounded RSI R1
- [x] candidate worktree
- [x] baseline/candidate 자동 benchmark
- [x] promotion report
- [x] human-approved merge
- [x] FORGE headless 자기수정 (`forge:<goal>` 구동)

### P3 — Automation durability
- [ ] Scheduled/Deferred/Condition semantics
- [ ] idempotency / timezone / restart

### P4 — Tool 효율
- [ ] Tool Script/RPC Mode

## 원칙

FORGE는 "싼 모델을 쓰는 제품"이 아니다.

**저렴한 모델의 약점을 Harness의 검증·복구·승격·계측으로 통제하여, 강한 모델에만 의존하지 않고도 믿을 수 있는 결과를 만드는 시스템**이다.
