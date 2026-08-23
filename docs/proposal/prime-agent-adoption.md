# Prime Agent 기술 도입 제안

> 상태: Proposal
> 대상: PrimeIntellect `prime-agent`
> 목표: Prime Agent의 Continual Harness, programmatic tool orchestration, recursive worker 아이디어를 FORGE의 핵심 철학에 맞게 선택적으로 도입한다.

## 1. 결론

Prime Agent를 복제하지 않는다.

FORGE가 가져올 핵심은 다음 네 가지다.

1. **Evidence-backed Continual Harness refinement + rollback**
2. **Restricted Tool Script / RPC**
3. **Bounded Recursive Workers**
4. **Heartbeat / Autonomous Budget**

FORGE의 차별점은 그대로 유지한다.

> **저렴한 모델을 쓰는 것이 목적이 아니라, 저렴한 모델도 강한 실행·검증·수리·복구 프로세스 안에서 높은 품질의 결과를 내도록 만드는 것이 목적이다.**

따라서 모든 도입은 `success_rate / correctness`와 deterministic verification을 우선하고, 비용은 성공 품질을 유지한 뒤 최적화한다.

---

## 2. Prime Agent에서 얻는 핵심 인사이트

Prime Agent의 강점은 단순 모델 성능보다 Harness에 있다.

개념적으로 다음 구조를 사용한다.

```text
Persistent Environment
├─ Programmatic Tool Use
├─ Recursive/Sub Agents
├─ Skills / Memory
└─ Continual Harness Refinement
```

FORGE와 방향은 유사하지만 강조점이 다르다.

```text
Prime Agent
Persistent environment
+ recursive execution
+ continual harness

FORGE
Bounded execution
+ deterministic verification
+ repair/escalation
+ durable recovery
+ measured quality/cost
```

FORGE는 Prime의 장점을 가져오되 Verification-driven Quality를 중심축으로 유지한다.

---

# A. Continual Harness Refinement

## 3. 현재 FORGE와의 차이

FORGE는 이미 다음 기반을 가진다.

```text
Curated Skills
Learned Skills
Project Skills

Telemetry
Deterministic Benchmark
RSI Promotion Gate
```

하지만 Skill/Memory/Prompt 개선은 아직 완전히 닫힌 feedback loop가 아니다.

목표는 실행 결과에서 얻은 evidence를 작은 durable improvement로 축적하는 것이다.

```text
Run
 ↓
Verification / Telemetry
 ↓
Reflection
 ↓
Refinement Candidate
 ↓
Benchmark / Evidence Gate
 ↓
Accept or Reject
 ↓
History + Rollback
```

## 4. 수정 가능한 대상

초기에는 FORGE runtime code 전체를 자동 변경하지 않는다.

낮은 위험도부터 시작한다.

### Level 1

- Learned Skill
- Project Skill
- Memory

### Level 2

- supplemental role instruction
- tool usage hint
- routing hint

### Level 3

- Agent runtime source code

Level 3은 기존 bounded RSI candidate worktree 경로에서만 수행한다.

## 5. Base Prompt 불변성

기본 system prompt를 매 실행 결과에 따라 직접 덮어쓰지 않는다.

```text
Base Prompt (version controlled)
        +
Supplemental Refinement
```

구조를 우선한다.

이렇게 하면 잘못된 학습을 rollback하기 쉽고 prompt drift를 줄일 수 있다.

## 6. Evidence Requirement

단 한 번 성공했다고 Global/Learned Skill로 자동 승격하지 않는다.

Refinement에는 근거를 남긴다.

예:

```text
RefinementCandidate
- type
- scope
- proposed_change
- evidence_runs
- failure_pattern
- expected_effect
- created_at
```

가능하면 다음 데이터를 연결한다.

- verification result
- repeated failure count
- Debugger/repair activation
- token/model call change
- cost_per_success

## 7. 사용자 투명성

자동 학습이 내부에서 조용히 일어나지 않게 한다.

예:

```text
이번 작업에서 학습

Learned Skill 후보
"Vue production build verification"

근거
- 동일 유형 실패 3회
- build_frontend 후 해결

[승인] [무시]
```

Global 영향 범위가 큰 변경은 사용자 승인 기본값을 유지한다.

## 8. Rollback

모든 refinement는 history를 가진다.

```text
Refinement
v1 → v2 → v3
       ↑
    rollback
```

최소 저장 정보:

- before
- after
- reason/evidence
- timestamp
- benchmark delta if available

---

# B. Restricted Tool Script / RPC

## 9. 문제

현재 일반적인 tool loop는 작은 탐색마다 모델 왕복을 만든다.

```text
LLM → grep
LLM → read A
LLM → read B
LLM → git diff
LLM
```

이 구조는 저렴한 모델을 사용하더라도 latency와 context 증가를 만든다.

## 10. Prime의 programmatic orchestration에서 가져올 것

Prime처럼 unrestricted IPython 전체를 모델에게 제공하는 것을 기본 설계로 삼지 않는다.

FORGE에는 제한된 Tool RPC가 더 적합하다.

```text
LLM
 ↓
Restricted Tool Program
 ├─ grep
 ├─ read_file
 ├─ git_status
 ├─ git_diff
 └─ test result collect
 ↓
Aggregated Result
 ↓
LLM
```

## 11. 초기 허용 범위

v1은 read-only operation만 묶는다.

예:

- grep + 여러 read_file
- 여러 파일 read
- git status + diff
- test/build 결과 수집
- repository exploration

Mutation은 기존 tool/approval/verification 경로를 유지한다.

## 12. 보안

다음 방식은 피한다.

```text
LLM → arbitrary Python → host
```

대신 허용된 RPC 이름과 argument schema만 실행한다.

```text
ToolScript
[
  {"tool":"grep", ...},
  {"tool":"read_file", ...}
]
```

각 operation은 기존 workspace boundary와 security policy를 그대로 통과한다.

## 13. 성공 조건

Benchmark에서 다음을 확인한다.

- success_rate 유지 또는 향상
- model round-trip 감소
- prompt token 감소
- elapsed 감소
- cost_per_success 감소

성공률이 떨어지면 도입하지 않는다.

---

# C. Bounded Recursive Workers

## 14. 목적

Prime의 recursive/subagent 개념은 긴 복합 작업에서 가치가 있다.

하지만 FORGE는 worker 수를 늘리는 것 자체를 목표로 하지 않는다.

병렬화 가능한 독립 작업에서만 사용한다.

```text
Developer / Coordinator
       ↓
Dependency Check
   ┌───┴────┐
   ↓        ↓
Worker A  Worker B
   └───┬────┘
       ↓
Result Aggregate
       ↓
Verification
```

## 15. Worker 생성 조건

다음 조건을 모두 만족할 때만 고려한다.

- 작업이 실제로 독립적
- shared file 충돌 위험이 낮음
- 병렬 실행으로 elapsed 감소 가능
- 추가 context/token 비용보다 이득이 큼

단순 작업에는 worker를 생성하지 않는다.

## 16. Context 전달

Parent context 전체를 복사하지 않는다.

각 worker는 self-contained task packet을 받는다.

```text
WorkerTask
- goal
- relevant files
- constraints
- expected output
- verification hint
```

이 방식으로 multi-agent context duplication을 제한한다.

## 17. Mutation 격리

초기에는 같은 working tree에 여러 worker가 동시에 쓰지 않는다.

후보:

- read-only research worker
- isolated worktree worker
- 파일 ownership이 명확한 worker

결과 merge 후 최종 verification을 반드시 수행한다.

---

# D. Heartbeat / Autonomous Budget

## 18. 목적

FORGE는 Durable Resume와 Scheduler를 갖추기 시작했지만 장시간 autonomous execution에는 별도 budget이 필요하다.

예:

```text
Autonomous Run
├─ max wall time
├─ max model calls
├─ max estimated cost
├─ max repair attempts
└─ heartbeat
```

## 19. Heartbeat

장시간 작업은 일정 주기로 상태를 durable하게 남긴다.

```text
heartbeat
- current task
- current phase
- last progress
- model calls
- estimated cost
- verification state
```

Heartbeat 자체가 LLM 호출을 발생시키지 않게 한다.

## 20. Budget Gate

예산을 초과하면 무한 실행하지 않는다.

```text
Budget reached
→ safe checkpoint
→ pause
→ 사용자에게 현재 상태/남은 작업 보고
```

비싼 모델 escalation도 budget에 포함한다.

---

# E. FORGE의 Verification Advantage

## 21. 가장 중요한 차별화

Continual Harness와 recursive worker가 추가되어도 FORGE의 최종 판단자는 모델이 아니다.

```text
Cheap / Efficient Model
        ↓
Harness
        ↓
Execution
        ↓
Deterministic Verification
     ↙      ↘
  FAILED    PASSED
    ↓          ↓
Repair /     Commit
Escalate
```

핵심 invariant:

> 모델의 `완료했습니다`는 완료 조건이 아니다.

완료는 가능한 범위에서 build/test/checker 등 프로세스가 결정한다.

## 22. 비용 철학

다음 최적화는 잘못된 것이다.

```text
더 싼 모델
→ 성공률 하락
→ retry 증가
→ 결국 더 비쌈
```

FORGE의 평가 순서는 다음과 같다.

1. correctness / success_rate
2. verified completion
3. cost_per_success
4. elapsed
5. human intervention

Flash 사용률이나 token/task 자체는 최상위 KPI가 아니다.

---

# F. Bounded RSI와의 통합

## 23. 두 개선 루프

FORGE에는 장기적으로 두 개의 자기개선 경로를 둔다.

### Harness Refinement Loop

낮은 위험도, 빈번한 개선.

```text
Run
→ Evidence
→ Skill/Memory/Supplemental Prompt Candidate
→ Gate
→ Apply
→ Rollback 가능
```

### Source RSI Loop

높은 위험도, 엄격한 개선.

```text
Baseline FORGE
→ Candidate Worktree
→ Source Change
→ Fixed Benchmark
→ Promotion Gate
→ Human Approval
→ Merge
```

두 경로를 섞지 않는다.

## 24. Promotion 원칙

이미 존재하는 lexicographic gate 철학을 유지한다.

```text
success_rate regression
→ reject

success_rate 유지
→ cost_per_success 비교

비용도 유사
→ elapsed 비교
```

Security/test regression은 즉시 reject한다.

---

# G. 단계별 구현

## Phase P0 — Refinement History

- refinement candidate 모델
- evidence 연결
- before/after history
- rollback
- Learned/Project Skill부터 적용

## Phase P1 — Transparent Refinement UX

- 작업 종료 후 학습 후보 표시
- 승인/무시
- 적용 이력
- rollback UI/API

## Phase P2 — Restricted Tool Script

- read-only RPC batch
- aggregated output
- benchmark A/B

## Phase P3 — Bounded Workers

- read-only/research worker부터
- self-contained task packet
- token/cost budget
- deterministic final verification

## Phase P4 — Autonomous Budget

- wall time/model call/cost/repair budget
- non-LLM heartbeat
- safe pause

## Phase P5 — Source RSI Integration

- candidate worktree
- fixed benchmark
- existing promotion gate 연결
- human promotion

---

# H. Benchmark

각 Phase는 기존 deterministic benchmark로 전후 비교한다.

필수 지표:

- success_rate
- verified completion rate
- cost_per_success
- elapsed_p50
- model calls
- token usage
- repair activation
- human intervention

Continual refinement는 추가로:

- refinement 적용 횟수
- rollback 횟수
- 동일 실패 재발률
- skill/refinement별 성공률 변화

를 측정한다.

---

# I. 하지 않을 것

현재는 다음을 하지 않는다.

- Prime Agent 전체 복제
- unrestricted IPython host execution
- 모든 task에 subagent 생성
- worker context 전체 복제
- 자동 main merge
- evidence 없는 prompt 자기수정
- 자동 Global Skill 오염
- LLM-as-a-judge를 최종 품질 gate로 사용
- benchmark 없이 모델 routing 변경
- 비용 절감을 위해 verification 약화

---

# J. 도입 우선순위

```text
1. Continual Harness refinement + rollback
2. Restricted Tool Script / RPC
3. Bounded Recursive Workers
4. Heartbeat / Autonomous Budget
5. Source RSI와 통합
```

단, 현재 verification/reliability에 미해결 P0 문제가 있다면 그것을 먼저 해결한다.

---

## 완료 기준

Prime Agent 기술 도입이 성공했다고 판단하려면 다음을 만족해야 한다.

1. 실행 경험이 evidence-backed refinement로 축적된다.
2. 잘못된 refinement를 rollback할 수 있다.
3. 학습 내용과 근거가 사용자에게 보인다.
4. Tool Script가 model round-trip을 줄이면서 성공률을 떨어뜨리지 않는다.
5. Worker는 독립 작업에서만 bounded하게 생성된다.
6. 장시간 작업이 명시적 budget 안에서 동작한다.
7. 모든 변경의 최종 품질 판단은 deterministic verification을 우선한다.
8. benchmark에서 success_rate를 유지하면서 cost_per_success 또는 elapsed가 실제로 개선된다.

## 최종 방향

Prime Agent에서 가져와야 할 것은 특정 UI나 기능 목록이 아니라 **Harness가 실행 경험을 축적하고 프로그램적으로 도구와 하위 작업을 조직하는 방식**이다.

FORGE는 여기에 더 강한 Verification/Repair/Recovery 경계를 결합한다.

> **Efficient Model + Continually Improving Harness + Deterministic Verification + Repair/Recovery = Reliable Autonomous Development**

이 조합을 FORGE의 장기 경쟁력으로 삼는다.

---

# 구현 상태 — A의 P0 커널 (2026-08-23)

**구현됨(적용은 아직 없음).** 실행 경험을 evidence로 모아 개선 후보를 만들고 보여주는 뼈대까지다.
승인해도 파일은 바뀌지 않는다 — 실제 적용(applier)은 다음 단계다.

```text
run 종료(finish)
 ↓ _reflect  (backend/app/runtime/agent.py)
eventlog의 verify_failed → 실패 서명 정규화 (refine.failure_signature)
 ↓ 서로 다른 run 2회 이상 반복?  (refine.MIN_EVIDENCE_RUNS)
RefinementCandidate 저장 (refinements 테이블, before/after 포함)
 ↓ refinement_candidate 이벤트
UI 카드 → [승인] [무시] → [되돌리기]
```

- **근거**: `evidence_runs`(반복된 run 목록) + `evidence`(final_status·repair_used·succeeded·session_cost_usd).
  전역 `cost_per_success`는 기존 `/api/metrics/summary`가 이미 제공한다(중복 계산 안 함).
- **1회 학습 금지**: 서로 다른 run에서 같은 서명이 2회 이상 관측돼야 후보가 된다. 한 run 안의
  최초 실패 + 수리 후 실패는 1회로 센다(done 이벤트로 run을 나눈다).
- **scope**: 항상 `project`. Learned/Global 자동 승격 없음(전역 오염 방지).
- **Base Prompt 불변**: 후보 대상은 Project Skill 파일뿐. 프롬프트 자기수정 경로 없음.
- **rollback**: `before_text`/`after_text`를 함께 저장하고, 결정은 `pending↔approved|ignored`로 되돌린다.
- **중복 제안 금지**: 같은 `failure_pattern`의 후보는 한 번만 만든다(무시한 후보를 되살리지 않는다).
- **LLM 없음**: 후보 생성은 전부 결정적 규칙이다. LLM-as-judge 게이트 없음.

관련 파일: `backend/app/runtime/refine.py`(순수 로직) · `agent.py::_reflect` ·
`app/db/models.py::Refinement` · `store.save_refinement/list_refinements/decide_refinement` ·
`GET /api/rooms/{id}/refinements` · `POST /api/refinements/{id}/decide` ·
테스트 `backend/test_refinement.py`.

적용(applier) 구현됨(2026-08-23): 승인 시 후보를 Project/Learned skill 파일(.md)에 실제 적용하고,
되돌리기는 before_text로 원상복구한다(Base Prompt 불변). `routes._apply_refinement_file`.

다음(미구현): 적용 전후 벤치 자동 비교,
supplement 타입(`type="supplement"`) 후보 생성.
