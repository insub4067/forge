# Bounded Recursive Self-Improvement 제안

> 상태: Proposal
> 목표: FORGE가 자기 자신(프롬프트·정책·도구·코드)을 개선하되, main을 직접 덮어쓰지 않고
> 고정 benchmark로 검증한 뒤에만 승격하는 안전한 자기개선 루프를 설계한다.

## 1. 배경

FORGE에는 이미 **약한 자기개선**이 있다.

- Reviewer ↔ Debugger 상태 기반 자기수정 루프
- `save_skill`로 성공 절차를 재사용 가능한 skill로 축적
- Global + Workspace 2-tier skill 재사용

없는 것은 **자기 코드/정책을 telemetry 근거로 바꾸고, 개선을 계측으로 증명해 반영하는 경로**다. 현재 telemetry(`agent_runs`)와 병목 진단(`metrics.py`)은 데이터를 수집·표시만 하고, 그 데이터가 FORGE를 바꾸지 않는다.

이 문서는 그 빈틈을 **bounded** 방식으로 메운다. 핵심 제약은 하나다.

> FORGE는 자기 코드를 절대 main에 직접 덮어쓰지 않는다.

## 2. 절대 원칙

```text
Telemetry / Benchmark
      ↓
개선안(candidate)
      ↓
candidate branch / worktree
      ↓
수정
      ↓
고정 benchmark 실행
      ↓
기존 버전과 비교
      ↓
개선이면 promotion(사람 승인) / 악화면 rollback(자동)
```

- main 직접 수정 금지. 모든 변경은 격리된 worktree/branch에서.
- 승격은 **사람 승인**을 거친다(초기에는 자동 승격 없음).
- 악화·동률·미검증은 **자동 폐기**가 기본값.
- 실측 없는 최적화 금지 — benchmark가 유일한 판정자다.

## 3. 평가 우선순위 (엄격한 사전식 순서)

지시된 순서를 그대로 게이트로 만든다. 앞 기준을 해치면 뒤 기준의 이득은 **무효**다.

```text
1. success rate 유지/향상   (절대 후퇴 불가 — non-inferiority 게이트)
2. cost per successful task 감소
3. elapsed time 감소
4. human intervention 감소
```

핵심: **토큰 절감 자체가 목표가 아니다.** 성공률을 유지하면서 성공 작업당 비용을 낮추는 것이 목표다. 성공률이 떨어지면 비용이 아무리 줄어도 candidate는 탈락한다.

## 4. 이미 있는 것 (재사용)

새 인프라를 짓기 전에 현재 자산을 그대로 쓴다.

| 필요 | 현재 자산 |
|---|---|
| per-run telemetry | `agent_runs`(model_calls·tokens·cache·elapsed_ms·retries·debugger·pro·final_status·selected_skills) |
| 비용 모델 | `metrics.py` `run_cost`/`sum_cost` (config `MODEL_PRICING`) |
| 성공 정의 | `sessions.final_status == "completed"` |
| 집계·병목 rule | `/api/metrics/summary`, `metrics.py bottlenecks` |
| 고정 작업 | `docs/operations/benchmark.md` 작업 A~F |
| 격리 실행 | git worktree |

즉 telemetry·cost·success 정의는 **이미 존재**한다. RSI 루프는 이것을 **자동 실행·비교·게이트**로 엮는 것이다.

## 5. 고정 Benchmark 하네스 (선결 조건)

RSI의 신뢰도는 benchmark의 질에 100% 종속된다. 이게 먼저다.

### 5.1 결정성 문제

LLM 출력은 비결정적이다. 단일 실행 1회 비교는 노이즈다. 따라서:

- 각 작업을 **N회**(예: 5) 실행하고 성공률·비용을 분포로 본다.
- 채점은 **결정적**이어야 한다 — 작업마다 기계 판정 가능한 성공 기준(테스트 통과, 특정 파일 diff, grep 매치)을 정의한다. "모델이 잘한 것 같다"는 채점 금지.

### 5.2 benchmark 확장

현재 A~F 6개는 통계적 판정에 부족하다. 성공률 non-inferiority를 논하려면 작업 수 × 반복 수가 필요하다. 초기 목표: 작업 12~20개 × 5회. 각 작업은 격리된 fixture repo에서 실행(부작용 없음, 재현 가능).

### 5.3 인터페이스(개념)

```text
run_benchmark(agent_version, tasks, repeats) -> BenchmarkResult
  BenchmarkResult:
    success_rate
    cost_per_success        # metrics.sum_cost / successes
    elapsed_p50
    human_interventions     # 승인/질문 발생 수
    per_task breakdown
```

## 6. 무엇을 자기수정 대상으로 하는가 (blast radius 순)

작은 폭발 반경부터. 코어 루프 재작성은 마지막이다.

1. **프롬프트/정책** (최소 위험): role system prompt, triage 기준, skill 선택 budget, thinking effort, 난이도 판정 임계값.
2. **모델 라우팅**: role별 flash/pro 승격 조건.
3. **도구/스킬**: 새 skill 저장, 도구 설명 개선.
4. **코어 로직** (최대 위험): agent loop, recovery, compaction — **초기 범위 제외**. 사람이 직접 수정.

초기 RSI는 1~2단계만 다룬다. 대부분의 비용 이득(§metrics: planner 63%)은 프롬프트/라우팅 조정으로 얻을 수 있다.

## 7. 루프 상세

```text
1. Observe   telemetry 집계 → 병목 rule(metrics.bottlenecks)에서 개선 후보 도출
2. Propose   후보 하나에 대한 구체적 변경안 생성(예: "reviewer thinking effort 하향")
3. Isolate   git worktree + candidate branch 생성
4. Mutate    변경 적용(프롬프트/config diff — 코어 로직 아님)
5. Evaluate  고정 benchmark N회 실행 → BenchmarkResult
6. Compare   baseline(현재 main)과 사전식 게이트로 비교
7. Decide    통과 → promotion 후보 큐(사람 승인) / 실패 → worktree 폐기 + 기록
```

한 번에 **후보 하나**만. 여러 변경을 섞으면 무엇이 효과였는지 귀속 불가.

## 8. 비교 게이트 (사전식)

```text
if candidate.success_rate < baseline.success_rate - ε_sr:   REJECT   # 성공률 후퇴 절대 불가
elif candidate.cost_per_success < baseline * (1 - ε_cost):  PROMOTE_CANDIDATE
elif cost 동률 and candidate.elapsed_p50 < baseline:        PROMOTE_CANDIDATE
elif 위 동률 and candidate.human_interventions < baseline:  PROMOTE_CANDIDATE
else:                                                       REJECT
```

- ε_sr: 성공률 허용 후퇴(권장 0 — 후퇴 불허). 노이즈 흡수용 신뢰구간은 두되 점추정 후퇴는 막는다.
- 동률·미검증은 REJECT. **기본은 폐기**다.

## 9. Promotion / Rollback

- **Promotion**: 게이트 통과 candidate는 자동 병합하지 않는다. diff·benchmark 결과를 사람에게 제시 → 승인 시에만 main 반영. 승인 후에도 이전 버전 SHA를 rollback 포인트로 보존.
- **Rollback**: 승격 후 라이브 telemetry가 악화(성공률↓/비용↑)를 보이면 보존한 SHA로 되돌린다. 초기에는 자동 감지 + 사람 승인 rollback, 향후 조건 충족 시 자동 rollback 검토.
- **감사 로그**: 모든 candidate(채택/폐기)의 변경 diff·benchmark 결과·결정을 기록. 자기개선 이력 자체가 telemetry가 된다.

## 10. 안전 경계 (반드시)

RSI는 에이전트가 자기 실행 환경을 바꾸는 것이라 오늘 보안 리뷰의 연장선이다.

- **main 쓰기 금지** — candidate는 worktree/branch에만. 병합은 사람 승인 경로로만.
- **코어 로직 자기수정 초기 제외** — 프롬프트/config만.
- **prompt injection 격리** — 웹·외부·workspace 콘텐츠가 "너 자신을 이렇게 바꿔라"를 시켜도 self-mutation trigger가 되지 않는다. 개선안 도출은 오직 내부 telemetry에서만.
- **benchmark 격리** — fixture repo에서만 실행, 실제 사용자 데이터·workspace 건드리지 않음.
- **비용 상한** — benchmark N회 실행 자체가 토큰을 쓴다. RSI 사이클당 예산 상한을 두고, 절감 이득이 benchmark 비용을 넘을 때만 의미가 있다.
- **동시성** — candidate 실행이 사용자의 실사용 세션과 자원을 다투지 않게 스케줄(유휴 시간 우선).

## 11. Telemetry (RSI 자체 계측)

- candidate 수, promotion/reject 비율
- 사이클당 benchmark 비용
- 승격된 변경의 라이브 성공률/비용 실측(예측 대비 검증)
- rollback 발생 수

RSI가 실제로 cost per successful task를 낮추는지를 RSI 스스로 계측해 판단한다. 낮추지 못하면 RSI 루프 자체를 중단한다.

## 12. 단계

### R0 — Benchmark 자동화 (선결) — ✅ 구현됨
- `backend/bench.py` + `backend/bench_tasks.py`: 21개 결정적 task(카테고리 21종, COMPLEX 5),
  fixture 격리, N회 반복, 채점(테스트/파일/grep), 집계·JSON 출력, 세션 자동 정리.
- `backend/test_bench_quality.py`: 정답 노출·다양성·trivial 비중·중복·상태오염 검사.
- 실험 플래그(기본 off): `FORGE_PLANNER_FLASH/PLANNER_OFF/SKILLS_OFF`로 Pro/Flash/No-Planner·skills on/off A/B.
- `backend/rsi.py` `promotion_gate`: 사전식 판정(success_rate→cost→elapsed) 코드화, self-test 통과.

### R1 — 수동 candidate 평가
- 사람이 프롬프트/config 변경안을 worktree에 적용 → `run_benchmark`로 baseline 대비 게이트 판정.
- RSI의 "판정기"를 사람이 트리거해 신뢰도부터 확인.

### R2 — 자동 제안
- `metrics.bottlenecks`에서 변경안 자동 도출 → worktree → benchmark → 게이트 → **사람 승인 큐**.

### R3 — Promotion/Rollback 운영
- 승인 기반 병합, rollback 포인트 보존, 라이브 검증, 감사 로그.

### R4 — 범위 확장 (신중)
- 라우팅·skill까지. 코어 로직은 충분한 신뢰가 쌓인 뒤에만, 그마저 사람 승인 필수.

## 13. 하지 않을 것

- main 자동 덮어쓰기
- 코어 agent loop 자기수정(초기)
- 사람 승인 없는 promotion(초기)
- 단일 실행 1회로 성공률 판정
- 외부/웹 콘텐츠 기반 self-mutation
- Multi-Agent 오케스트레이션·Vector DB·별도 학습 파이프라인(측정된 필요 없음)
- benchmark 없이 "느낌"으로 채택

## 14. 완료 기준

1. main을 직접 수정하지 않고 candidate를 worktree에서 평가한다.
2. 고정 benchmark가 결정적·반복 실행으로 success rate와 cost per success를 낸다.
3. 성공률 후퇴 candidate는 비용이 아무리 낮아도 REJECT된다.
4. promotion은 사람 승인을 거친다.
5. 악화 시 보존된 SHA로 rollback 가능하다.
6. 모든 candidate 결정이 감사 로그에 남는다.
7. prompt injection이 self-mutation을 유발하지 못한다.
8. RSI 자체 비용이 telemetry로 계측되어, 이득이 없으면 중단 판단이 가능하다.

## 결론

FORGE의 자기개선은 자기 코드를 main에 바로 쓰는 것이 아니다.

> **Telemetry → Propose → Isolate → Benchmark → 사전식 게이트 → 사람 승인 Promotion / 자동 Rollback**

이 좁은 루프로, 성공률을 지키면서 성공 작업당 비용을 낮추는 방향으로만 스스로를 바꾼다. 가장 먼저 할 일은 전체 RSI가 아니라 **R0 — 결정적 고정 benchmark 하네스**다. 판정기가 신뢰할 수 없으면 나머지는 전부 위험한 자동화일 뿐이다.
