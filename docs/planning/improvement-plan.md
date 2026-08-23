# FORGE 개선 계획

> 기준: 2026-08-23 `main`

## 핵심 가치

과거의 "클로드급 성능을 저렴하게"라는 표현은 방향을 충분히 설명하지 못한다.

FORGE의 핵심은:

> **저렴한 모델로도 결과 품질을 보장할 수 있도록 실행·검증·수리·복구를 Harness 프로세스로 강제하는 것**

이다.

비용은 품질 다음이다. 최적화 순서는 `success_rate → verified completion → cost_per_success → elapsed → human intervention`이다.

## 이미 해결된 과거 핵심 문제

- 올인원 Developer로 역할 간 context 재전송 축소
- host/self-build 경로 확보
- Strict Verification Gate 도입
- 검증 실패 bounded repair
- step-level persistence
- Durable Auto Resume
- auto commit/push 경로
- event polling/seq dedup
- 3-tier Skills
- application HTTP/WebSocket auth
- deterministic R0 benchmark 21 tasks
- bounded RSI promotion gate

따라서 과거 문서의 "durable resume 미구현", "benchmark 실물 없음", "Planner 폭주가 현재 구조의 중심" 같은 항목은 더 이상 현재 backlog가 아니다.

## P0 — 검증 의미를 엄밀하게

현재 `_verify()`는 false failure를 줄이려 일부 pytest 비정상 종료를 통과시킬 수 있다.

다음:

- `PASSED / FAILED / UNAVAILABLE`
- 실행 불가/설정 오류/timeout은 UNAVAILABLE
- completion policy 명시
- FAILED/UNAVAILABLE에서 commit/push 우회 경로 테스트

## P1 — Resume 권한 안전성

Auto Resume은 실제 동작한다. 이제 "재시작했다고 권한이 확대되지 않는다"를 보장한다.

- 기존 승인 범위 기록/재사용
- 새 위험 mutation은 approval_required
- destructive/bash/write/git push 경계 테스트
- AUTO_RESUME=0 유지

거대한 permission framework는 만들지 않는다.

## P2 — Benchmark 현실성 확대

현재 21 task를 단순 숫자 증가보다 failure-mode coverage 중심으로 확장한다.

- multi-file/integration
- frontend/backend
- failing-test debugging
- ambiguous requirement
- long-running/restart
- 잘못된 사용자 가정 검증
- no-change가 정답인 task

외부 harness 비교도 동일 fixture/checker를 사용한다.

## P3 — Bounded RSI R1

`backend/rsi.py` promotion gate는 구현됐다. 다음은 orchestration이다.

```text
candidate worktree
→ FORGE 자기수정
→ 동일 benchmark
→ baseline 비교
→ promotion report
→ 사람 승인
```

자동 merge는 아직 하지 않는다.

## P4 — Automation durability

예약 기능은 존재한다. 다음은 기능 수보다 semantics다.

- restart
- duplicate 방지/idempotency
- timezone/DST
- retry/history
- Deferred/Condition

## P5 — Tool 효율

Tool Script/RPC는 성공률을 유지하면서 탐색 model round-trip을 줄일 수 있을 때만 도입한다.

## P6 — Skills / Model Routing

Skill과 model tier는 신념이 아니라 benchmark로 평가한다.

- Skill ON/OFF 및 scope별 효과
- Flash-first vs 강한 model 정책
- escalation이 실제 성공률을 얼마나 회복하는지

**싼 모델을 끝까지 고집하는 것이 목표가 아니다. Harness가 싼 모델을 최대한 활용하고 필요한 순간에만 강한 모델을 쓰게 만드는 것이 목표다.**

## 하지 않는다

- 실측 없는 Vector DB
- 무분별한 Multi-Agent
- 자동 main merge
- 기능 수를 위한 framework 추가
- 품질을 희생하는 token 절감

## 반복 사이클

```text
문제/가설
→ 최소 변경
→ deterministic test
→ benchmark
→ success-rate gate
→ cost/time 비교
→ Keep / Revert
```

FORGE의 개선은 "더 싸졌는가"가 아니라 **"품질을 유지하면서 더 효율적으로 검증된 성공을 만들었는가"**로 판단한다.
