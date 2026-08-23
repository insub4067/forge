# FORGE — 작업 진행 상태

> 마지막 갱신: 2026-08-23 `main`

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

남은 결함: 현재 pytest exit code 처리에서 실행/설정 오류 일부가 false failure 방지를 위해 통과될 수 있다. `PASSED / FAILED / UNAVAILABLE` 3상태로 분리하는 것이 다음 신뢰성 작업이다.

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
- [ ] verification `PASSED / FAILED / UNAVAILABLE`
- [ ] failed/unavailable에서 commit/push invariant 테스트
- [ ] resume-safe approval/capability

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
