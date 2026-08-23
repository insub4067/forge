# FORGE Benchmark

## 목적

Benchmark는 단순 비용 측정이 아니다.

> **저렴한 모델을 사용해도 Harness가 실제 결과 품질을 유지하는지 먼저 증명하고, 그 조건 안에서 성공 작업당 비용을 낮춘다.**

판단 순서:

1. `success_rate` / deterministic correctness
2. verification reliability
3. `cost_per_success`
4. elapsed
5. human intervention

성공률이 후퇴한 후보는 비용이 낮아도 개선이 아니다.

## R0 Harness

`backend/bench.py` + `backend/bench_tasks.py`는 격리 fixture에서 Agent를 실행하고 deterministic checker로 결과를 채점한다. 현재 25개 task가 있다.

```bash
cd backend
python bench.py --self-test
python bench.py --run --repeat 3
```

`test_bench_quality.py`가 checker와 task 품질을 검증한다. correctness authority로 LLM judge를 사용하지 않는다.

## 측정값

- success_rate
- cost_per_success
- elapsed_p50
- prompt/completion/cache tokens
- model/tool calls
- Pro escalation
- retries/repair
- verification outcome

## 현재 Model 실험 방향

현재 기본 Runtime은 별도 Planner/Reviewer/Debugger가 없는 올인원 Developer 구조다. 과거 Planner Pro/Flash/Off 실험은 역사적 최적화 기록이며 현재 기본 구조의 authority가 아니다.

앞으로는 동일 task에서 Developer model/tier, thinking policy, Skills on/off 등을 비교하되 success-rate gate를 먼저 적용한다.

Skill이 token을 더 써도 성공률을 높여 최종 `cost_per_success`를 낮춘다면 가치가 있다. token을 줄여도 실패가 늘면 regression이다.

## Reliability cases

지속적으로 다음을 결정적으로 검증한다.

- build/test failure를 완료로 오판하지 않음
- 검증하지 못한 상태를 검증 성공으로 기록하지 않음
- failed verification에서 commit/push하지 않음
- interrupted run이 restart 후 resume됨
- resume 재충돌이 무한 loop를 만들지 않음
- verified run만 최종 완료됨

## Bounded RSI

`backend/rsi.py` promotion gate:

```text
success_rate 후퇴 → REJECT
성공률 유지 → cost_per_success 비교
비용 동률 → elapsed 비교
전부 동률 → REJECT
```

PROMOTE 후보가 되어도 현재는 자동 main merge하지 않고 사람 승인을 유지한다.

### R1 orchestration 실행

`backend/rsi_run.py`가 candidate worktree에서 자기수정 → 재벤치마크 → 판정을 수행한다.

```bash
# baseline 측정 (1회)
python backend/bench.py --run --repeat 3 --tier auto --json baseline.json

# FORGE 자기수정 후 재벤치마크 (venv에서 실행 — API 비용 발생)
python backend/rsi_run.py --baseline baseline.json \
  --candidate-cmd "forge: bench task 21~25의 failing-test debugging 성공률을 높여라" \
  --repeat 3 --tier auto --json candidate.json --report report.md
```

- `forge:<goal>` — worktree 안에서 FORGE 에이전트를 headless 구동해 자기수정.
- 그 외 셸 명령 — 스크립트/프롬프트를 그대로 실행.
- `report.md`에 PROMOTE/REJECT 판정과 baseline 대비 표가 생성된다. merge는 사람이 결정한다.

## 확장 방향

25개 task를 기반으로 현실 난이도와 failure-mode coverage를 늘린다.

- multi-file feature/refactoring
- failing-test debugging
- frontend/backend 통합
- ambiguous requirement
- long-running/resume
- 잘못된 사용자 가정을 코드에서 확인하는 task
- 수정하지 않는 것이 정답인 task

외부 harness와 비교할 때도 동일 fixture/checker를 사용한다.

FORGE의 benchmark는 **싸게 실행됐음을 증명하는 장치가 아니라, 저렴한 모델로도 품질을 유지할 수 있음을 증명하는 장치**다.
