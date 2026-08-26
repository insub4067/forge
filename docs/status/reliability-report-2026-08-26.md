# FORGE 신뢰성 실측 보고 (2026-08-26)

> 질문: **"FORGE가 실패했을 때 왜 실패했는지 알 수 있는가, 성공했다고 말할 때 정말 믿을 수 있는가?"**
> 이 보고는 그 답을 실측으로 낸다. 문서가 아니라 코드·테스트·CI·벤치 결과가 authority다.
> 원자료: `backend/bench-results/2026-08-26-38c2e5c/`(summary·runs·failures·environment).

## Current HEAD
| 항목 | 값 |
|---|---|
| SHA (벤치 실행 시점) | `38c2e5c` — backend 런타임은 현행(이후 커밋은 UI-only) |
| pytest | ✅ 242 passed (SANDBOX_MODE=host) |
| ruff | ✅ passed |
| frontend test / build | ✅ 24/0 / build OK |
| bench self-test | ✅ pass |
| checker 검증(reference PASS·idempotent·broken FAIL) | ✅ 25/25 |

## Benchmark — n=125 (25 task × 5, 멱등화된 checker)
| 지표 | 결과 |
|---|---|
| **verified_success_rate** | **0.976** (122/125) |
| **false_completion_rate** | **0.000** (0/125) — 가장 위험한 실패가 제로 |
| false_failure_rate | 0.016 (2/125) |
| cost_per_verified_task | $0.00717 |
| human_interventions / task | 0.0 |
| completed / completed_unverified / verification_failed | 24 / 98 / 2 |
| tool_calls / task · repair · pro_escalation · context_block | 8.25 · 0 · 0 · 0 |
| elapsed avg / p50 / p95 | 29.2 / 23.1 / 69.1s |
| total_cost · cost_per_task | $0.874 · $0.00699 |
| prompt / completion tokens | 7,138,171 / 272,934 |
| cache hit / miss tokens | 6,742,784 / 377,872 |

가장 중요한 KPI 4개: verified_success 0.976 · **false_completion 0.0** · intervention/task 0.0 · cost_per_verified $0.00717.

## Failures — 2건 (둘 다 false_FAILURE, false_completion 아님)
FORGE는 **한 번도 거짓 성공을 주장하지 않았다.** 2건 모두 "실제로 맞는데 스스로 verification_failed로 과차단"한 안전 방향 실패다. checker는 25/25 검증됐으므로 checker 오류가 아니다.

### ① N — 입력 검증 추가 · `GATE_EXECUTION_ERROR`
- Observed: gate R1=failed, R2=passed → verification_failed. 그러나 checker PASS(코드 정답).
- Root cause: FORGE가 **자기가 작성한 gate(R1)의 검증 명령이 결함**이라 정답 코드를 통과시키지 못했다. traceability도 R1 미검증으로 false_completion_candidate=True를 냈지만, 최종 상태는 완료가 아니라 verification_failed였다(강등이 아니라 과차단).
- Model failure ❌(코드 정답) · Checker failure ❌ · **Harness fix**: LLM-authored gate 명령 품질.

### ② W — long-running 상태 영속화 · `GATE_EXECUTION_ERROR`(내부 검증 비멱등)
- Observed: gate R1·R2·R3 전부 passed인데 verification_failed. checker PASS.
- Root cause: FORGE의 **내부 generic + integration 검증이 stateful `test_counter.py`를 2회 실행** → 2회차에 잔존 state.json 때문에 실패. 외부 벤치 checker는 이번에 멱등화(state.json 삭제)했지만, **FORGE 자체의 이중 검증**에는 같은 비멱등 문제가 남아 있다.
- Model failure ❌ · Checker failure ❌ · **Harness fix**: 내부 검증이 stateful 테스트에 비멱등.

## 핵심 질문 답
- **성공 주장을 믿을 수 있나?** → false_completion **0/125**. FORGE는 거짓 완료를 한 번도 내지 않았다.
- **실패 원인을 아는가?** → failures.json이 요구사항→gate→traceability→완료→checker chain을 11개 root-cause 카테고리로 남긴다. 2건 다 근본 원인까지 추적됨.

## 남은 P0 / P1 / P2 (실측 기반)
- **P0**: 없음. false_completion 0, 개입 0.
- **P1** — W 유형: 내부 검증(generic+integration)이 stateful 테스트를 다회 실행해 정답을 과차단. 드물고(1/125) 안전 방향이나 실사용의 상태 영속 작업에서 재발 가능. 수정안: 내부 검증을 clean 상태에서 1회만, 또는 stateful 감지 시 재실행 억제.
- **P2** — N 유형: LLM-authored gate 명령 품질(GATE_EXECUTION_ERROR). gate 자기검증 강화. 근절 어렵고 안전 방향이라 후순위.

## 재현
```bash
cd backend
SANDBOX_MODE=host .venv/bin/python verify_checkers.py           # checker 검증(무비용)
SANDBOX_MODE=host .venv/bin/python bench_baseline.py --repeat 5 --sha <sha>   # 실측(LLM 비용)
```
결과는 `bench-results/<date>-<sha>/`에 summary·runs·failures·environment로 저장된다.
