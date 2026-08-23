# FORGE Agent Loop

> 기준: 2026-08-23 `main`

FORGE의 Agent Loop는 **저렴한 모델을 쓰기 위한 비용 절감 트릭이 아니라, 저렴한 모델의 불확실성을 프로세스로 보완해 품질을 확보하는 Harness**다.

## 실행 흐름

```text
User
 ↓
Triage
 ├─ CHAT → Chat (Flash)
 └─ AGENT → Developer (Flash + thinking)
              ↻ Plan → Execute → Self-verify / Repair
              ↓ 막히면 Pro + stronger thinking
              ↓
         Strict Verification Gate
           ├─ PASS → completed
           └─ FAIL → repair 1회 → 재검증
                         ├─ PASS → completed
                         └─ FAIL → verification_failed
```

핵심은 두 층을 구분하는 것이다.

1. **Model loop**: Developer가 설계·구현·자체수정을 수행한다.
2. **Process gate**: 모델과 독립된 test/build 실행이 최종 완료 여부를 판정한다.

모델이 "완료했다"고 말해도 verification gate가 실패하면 완료가 아니다.

## 왜 올인원 Developer인가

Planner/Reviewer/Debugger를 별도 agent로 기본 호출하면 각 역할이 컨텍스트를 다시 읽어 비용과 지연이 증가한다. 현재는 한 Developer가 동일 컨텍스트에서 작업하고, 품질 authority는 별도 LLM Reviewer가 아니라 deterministic verification에 둔다.

따라서 **agent 수 감소는 비용 최적화**, **verification gate는 품질 보증**이라는 서로 다른 목적을 가진다.

## Model Policy

| 역할 | 기본 정책 |
|---|---|
| Triage | Flash, 경량 분류 |
| Chat | Flash, non-thinking |
| Developer | Flash + thinking, 막힘 시 Pro escalation |
| Vision | 필요 시 vision model |

Flash가 기본인 이유는 "싸기 때문"만이 아니다. 실패를 검출하고 수리하거나 강한 모델로 승격할 수 있는 Harness가 있기 때문에 낮은 모델 비용과 높은 완료 신뢰성을 함께 노릴 수 있다.

## Verification

현재 Runtime은 workspace에서 감지한 npm build/pytest를 실제 실행한다.

- PASS: `completed`
- FAIL: Developer에 실제 오류를 되먹여 bounded repair
- 재실패: `verification_failed`
- 검증 실패 경로는 commit/push 금지

향후 `검증 성공`, `실패`, `검증 불가`를 엄밀히 분리한다.

## Durable Resume

Agent step마다 history를 저장한다. 서버가 재시작되면 unfinished run을 찾아 저장된 history로 headless resume한다.

재시작은 품질 gate를 우회하지 않는다. resume된 run도 최종 verification을 통과해야 완료된다.

## Telemetry / Evaluation

최적화 판단 순서:

```text
success_rate
→ verified completion
→ cost_per_success
→ elapsed
→ human intervention
```

R0 benchmark는 deterministic checker로 결과물을 판정한다. 비용이 낮아져도 success_rate가 후퇴하면 정책 변경을 채택하지 않는다.

## Bounded RSI

FORGE는 자기 repository를 수정하고 benchmark 결과를 비교할 수 있다. `backend/rsi.py`에는 promotion gate가 있다.

하지만 candidate worktree 실행/merge는 아직 자동 폐루프가 아니며 최종 승인은 사람에게 둔다. 현재 목표는 무제한 자기수정이 아니라 **측정 가능한 bounded self-improvement**다.
