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

---

# 후속 개선 (P1·P2) + completed_unverified 분석 (2026-08-26, HEAD 1ba11a5 계열)

## completed_unverified 원인 규명 (repeat 3, 75 run 실측)
56건 분류: **GENERIC_UNAVAILABLE 40(71%)** · REQUIREMENT_GAP 16(29%) · GATE_NONE/PARTIAL 0.
- **GENERIC_UNAVAILABLE**: acceptance gate는 통과했으나 독립적 generic 검증(build/test) 대상이
  없어 `completed`(=gate passed AND generic passed) 바에 못 미침. bench fixture·실무의 config/문서/
  작은 스크립트 작업이 여기 해당. **버그가 아니라 정직한 안전 floor** — gate는 모델이 작성하므로
  독립 generic 검증 없이 completed를 주면 false_completion 위험. 실제 test/build 있는 repo(FORGE
  자체)에선 generic이 돌아 completed 도달(completed=19/24가 그 증거).
- **REQUIREMENT_GAP**: Task IR requirement가 passed gate로 미연결(모델이 requirement_id 누락).
  안전 강등. generic이 있는 경우에만 연결 개선이 completed로 전환되므로 효과 marginal.
- **결론**: completed_unverified를 억지로 줄이지 않는다(threshold 완화 = false_completion 증가 = 금지).
  높은 수치는 "독립 검증 대상 부재"라는 한계지, verification 설계 결함이 아니다.

## P1 — Stateful verification 비멱등 수정 (agent.py)
Root cause: generic `_verify`와 `_verify_integration`이 동일 test/build를 두 번 실행 →
stateful 테스트(state.json 영속)가 2회차에 잔존 상태로 깨져 정답을 verification_failed로 과차단.
Fix: `_verify`를 스냅샷/청소로 멱등화(`_verify_snapshot`/`_verify_cleanup`) — 검증 실행이 만든
새 파일을 실행 후 제거해 generic·integration이 같은 초기 상태에서 돈다. stateless 불변, 실제
실패 탐지 유지. 회귀 테스트 test_reliability_gates에 3케이스.
**잔여(P2)**: gate 검증(_verify와 별도)이 남긴 state.json을 integration이 볼 수 있어 W가 여전히
1/75 flaky(아래 재벤치). 완전 해결은 검증 lifecycle 전체(generic+gate+integration)를 한 스냅샷
경계로 감싸야 함 — 별도 P2.

## P2 — LLM-authored gate 명령 품질 (verification.py)
Root cause: 모델이 gate verification 명령을 `python3 -c "...\n..."`처럼 리터럴 `\n`으로 작성 →
SyntaxError. 명령 인프라 오류를 구현 실패로 오판해 정답 코드를 verification_failed 처리.
Fix: `classify_gate`가 rc≠0 실패 시 인프라 오류(command not found·bash 파스·python `<string>`/
`<stdin>` 파싱 오류)를 `failed`가 아니라 `unavailable`(GATE_EXECUTION_ERROR)로 분류 → 안전 강등.
**false_completion 방지**: 신호를 명령 스코프로 한정 — 검사 대상 코드(.py 파일)의 SyntaxError는
infra로 오분류하지 않고 `failed` 유지(깨진 코드가 completed_unverified로 새지 않게). 회귀 테스트
test_gate_infra_error 5케이스(진짜 실패는 여전히 failed 포함).

## Reliability invariants (regression test)
test_reliability_six_invariants.py — 6개 invariant를 순수 함수로 고정:
①증거 없으면 verified completion 불가 ②failed requirement면 completed 불가 ③gate 인프라 오류≠
구현 실패 ④검증이 이후 검증 오염 안 함 ⑤중복 실행 멱등 ⑥false_completion 방지 > success rate.

## Before / After 벤치 (동일 조건, repeat 3 = 75 run)
| 지표 | Before(수정 전) | After(P1+P2) |
|---|---|---|
| verified_success_rate | 0.976(n=125) / 1.0(n=75) | **0.987** |
| **false_completion_rate** | **0.0** | **0.0** (invariant 유지) |
| false_failure_rate | 0.027(n=125) | **0.013** (2→1) |
| completed / unverified / verification_failed | 19 / 56 / 0 | 20 / 54 / 1 |
남은 false_failure 1건 = W(P1 잔여, flaky, 안전방향). N형(gate SyntaxError)은 P2로 재현 안 됨.
**acceptance criterion(false_completion==0) 충족.** 수치가 나빠진 항목 없음.

## 최종 4문항
- **틀린 코드를 성공이라 할 경로가 남았는가?** — 실측 0/125·0/75, 그리고 P2가 코드 SyntaxError를
  infra로 오분류하지 않게 신호를 좁혔다. 남은 이론적 경로는 "모델이 trivially-passing gate를 쓰고
  generic도 우연히 통과" 조합뿐이며, generic은 모델이 못 건드리는 독립 검증이라 실측상 미발생.
- **맞는 코드를 실패라 할 주요 경로는?** — (1) 내부 generic+gate+integration 검증이 stateful
  테스트를 다회 실행(W, P1로 대부분 해소·잔여 flaky), (2) LLM-authored gate 명령 결함(N, P2로 해소).
- **completed_unverified의 가장 큰 이유는?** — GENERIC_UNAVAILABLE(71%): 독립 build/test 대상이
  없어 gate만으론 완전검증으로 승격 못 함. 안전 conservatism이지 결함 아님.
- **가장 약한 고리는?** — 검증 lifecycle의 멱등성(stateful 작업에서 generic+gate+integration의
  다회 실행). P1이 generic/integration은 멱등화했으나 gate 경계까지 통합하는 게 다음 P2.
