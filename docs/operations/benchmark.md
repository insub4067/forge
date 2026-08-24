# FORGE Benchmark

## 목적

Benchmark는 비용 순위표가 아니다.

> **Harness가 실제 결과 품질을 유지하는지 먼저 증명하고, 그 조건 안에서 성공 작업당 비용과 시간을 줄인다.**

판단 순서:

1. deterministic correctness / verified success
2. false-completion/verification reliability
3. `cost_per_success`
4. elapsed
5. human intervention

## R0 Harness

`backend/bench.py` + `backend/bench_tasks.py`는 임시 fixture workspace에서 Agent를 실행하고 **외부 deterministic checker**로 결과를 채점한다. 현재 **25개 task**다.

```bash
cd backend
python bench.py --self-test
python bench.py --run --repeat 3 --tier auto
```

`test_bench_quality.py`는 setup 직후 checker false, known fix 후 true 등을 검사해 checker false-positive/정답 노출을 방지한다. LLM judge는 correctness authority가 아니다.

## Task 범위

단일 파일 수정/bugfix뿐 아니라 다음을 포함한다.

- multi-file feature/refactor
- wrong import / recursive base case
- failing-test debugging
- ambiguous requirement
- state persistence/restart 성격 task
- frontend/backend 통합
- 수정하지 않는 것이 정답인 task
- 가정 검증/validation/config 등

## Runtime variants

현재 coding path는 **simple Developer 또는 auto complex Planner→Developer→fresh Reviewer**다. 과거 “항상 Planner” 또는 “Planner 없음” 실험 문구는 역사적이다.

비교 시 세션 model tier(`auto/flash/pro`), Skills policy, provider/model 등 실제 배선된 변수를 사용한다. 상위 MCP가 `plan`을 제공하는 경로도 별도 variant로 측정할 수 있다.

## 측정값

- success_rate / verified completion
- cost_per_success
- elapsed p50
- prompt/completion/cache tokens
- model/tool calls
- Pro escalation
- retries/repair
- gate/generic/integration outcome
- human intervention(확장 시)

## Reliability cases

Runtime test suite는 benchmark와 별개로 다음 invariant를 고정한다.

- test/build failure를 완료로 오판하지 않음
- unavailable을 passed로 승격하지 않음
- 코드 변경 + gate 0이 completed가 되지 않음
- gate recovery가 1회 상한을 넘지 않음
- failed verification에서 commit/push 금지
- completed_unverified push 금지
- interrupted run restart resume + crash-loop guard
- session auto_approve/model tier isolation
- compaction persistence
- project memory unsupported claim rejection

## Bounded RSI

`backend/rsi.py` promotion gate:

```text
success_rate 후퇴 → REJECT
성공률 유지 → cost_per_success 비교
비용 동률 → elapsed 비교
전부 동률 → REJECT
```

`backend/rsi_run.py`는 candidate worktree에서 command 또는 `forge:<goal>` 자기수정 → benchmark → report를 수행한다. candidate가 아무 변경도 만들지 않으면 noise 비교 전에 REJECT한다. PROMOTE 후보도 자동 main merge하지 않고 사람이 결정한다.

예:

```bash
python backend/bench.py --run --repeat 3 --tier auto --json baseline.json
python backend/rsi_run.py --baseline baseline.json \
  --candidate-cmd "forge: 특정 benchmark failure mode를 개선해라" \
  --repeat 3 --tier auto --json candidate.json --report report.md
```

## 해석 원칙

- token/task가 줄어도 success가 떨어지면 regression이다.
- cheap-first chain이 repair/escalation을 늘리면 strong-first보다 비쌀 수 있다.
- 단일 run latency 차이로 RSI promotion하지 않는다.
- Acceptance Gate는 모델이 만든 내부 검증이고 R0 checker는 외부 authority이므로, 둘의 불일치가 gate semantic quality를 측정하는 중요한 신호다.
