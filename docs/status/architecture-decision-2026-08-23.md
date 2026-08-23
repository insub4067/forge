# Agent 구조 단순화 결정 (2026-08-23)

> 구 다중역할 파이프라인(Planner/Coder/Reviewer/Debugger)을 **올인원 2역할
> (Developer + Vision)**로 단순화했다. 이 문서는 이유와 실측 근거를 남긴다.

## 왜 바꿨나

### 1. 에이전트 수 = 비용
에이전트가 하나 늘 때마다 그 역할이 **컨텍스트를 처음부터 다시 읽는 input token 비용**이
발생한다. 구 구조는 한 COMPLEX 작업에서 Planner→Coder→Reviewer↔Debugger로 역할을 여러 번
전환하며, 전환마다 `all_messages` 전체를 재전송했다. 관측된 비용 구조:

- planner가 실제 달러 비용의 **73%**(pro 모델 + 큰 컨텍스트 재전송).
- Reviewer/Debugger 루프는 flash라 싸지만 **역할 전환 왕복으로 시간이 폭주**.

### 2. 시간도 비용이다
구 구조에서 상태머신 설계 task(R)가 Reviewer↔Debugger 루프를 겉돌며 **621초**가 걸렸다.
성공은 했지만(비용 $0.0023로 최저), 사용자 체감 지연이 컸다. 역할 전환 churn이 원인이었다.

### 3. 한 두뇌가 끝까지 책임지는 게 낫다
DeepSeek 권고: 설계+구현+자체검증을 **flash + thinking medium** 한 모델이 처리하고,
**실패할 때만 pro로 승격**한다. 별도 Reviewer/Debugger에게 컨텍스트를 다시 넘기지 않으면
토큰·시간·API 호출이 모두 준다.

## 무엇을 바꿨나

| | 구 구조 | 신 구조(올인원) |
|---|---|---|
| 실행 역할 | Planner·Coder·Reviewer·Debugger | **Developer 하나** |
| 흐름 | Triage→(Planner)→Coder→Reviewer↔Debugger | Triage → Chat(최저가) \| Developer |
| 완료 판정 | Reviewer가 task 상태 done | Developer 자체검증(테스트/빌드) → 세션 final_status |
| 승격 | Debugger 반복 실패 시 pro | Developer 막힘 시 pro+think-high, 최대 2회 루프 |
| 단순 대화 | 별도 Chat 역할 | Triage가 최저가 flash Chat으로 분기(코드만 Developer) |

관리자 모델정책·집계에 노출되는 역할은 **triage / chat / developer / vision** 뿐이다
(과거 planner/coder/reviewer/debugger는 제외).

**Developer 루프**: `Plan(3줄) → Execute → Verify → PASS:완료 | FAIL:Diagnose→Repair→Verify`.
기본 flash+think-medium(Jr), 막히면(max_steps/repeated) pro+think-high로 승격해 최대
`MAX_ESCALATIONS=2`회 재시도(루프). 그래도 못 풀면 남은 문제를 사용자에게 보고한다.
무한 루프·비용 폭주는 step budget(45) + 반복 도구 호출 차단 + 승격 상한으로 막는다.

## 실측 결과 (R0 benchmark, COMPLEX 5개 task)

`backend/bench.py`로 격리 fixture + 결정론적 채점(테스트 통과) 측정. 구 구조 baseline은
동일 5개 task를 planner=PRO로 2회씩(10 runs) 측정한 값.

| 지표 | 구 구조 (PRO baseline) | 올인원 (Developer flash+think) | 변화 |
|---|---|---|---|
| success_rate | 1.0 (10/10) | 1.0 (5/5) | **유지** |
| **cost_per_success** | $0.00475 | **$0.00107** | **−77%** |
| elapsed_p50 | 21.6s | 11.8s | −45% |
| planner_tokens | 145,895 | 0 | 제거 |
| **task R (상태머신)** | **621.6s** | **8.1s** | **역할전환 churn 제거** |
| API 호출/작업 | Planner+Coder+Reviewer(+Debugger×N) | Developer 1 (+실패 시 승격) | **≤ 1/3** |

task별(올인원): C $0.00101 / D $0.00102 / G $0.00144(326s, 승격 루프) / Q $0.00110 / R $0.00076.

### 해석
- **성공률을 유지하면서 성공 작업당 비용을 77% 줄였다.** FORGE의 최상위 지표
  `cost per successfully completed task`가 목표대로 개선됐다.
- 역할 전환 제거로 R의 621초 → 8.1초. "시간도 비용"이 실측으로 확인됐다.
- 남은 느린 케이스(G, 326초)는 한 task가 승격 루프를 돈 것으로, 승격 상한(2회)이 시간을
  캡한다. 유형별 추가 분석 대상.

## 검증
- 회귀 7종 통과: `test_developer_loop`(정상·승격루프·중단·context·상한), runtime_efficiency,
  metrics, skills_scope, mcp_server, rsi, bench self-test.
- 기존 기능 보존: DeepSeek streaming/tool/thinking, Flash-first, compaction, reasoning
  recovery, Skills(3계층), approval, Docker sandbox, Postgres, telemetry, SSE, 예약 job, PWA.

## 향후: MCP External Planner
추론(계획)을 상위 모델(GPT/Claude, 정액 무제한)이 맡고 FORGE는 flash로 실행만 하는 구조로
확장한다. `forge_execute(goal, workspace, plan)`이 이미 있어 plan을 주면 Developer가 그대로
실행한다. 이러면 FORGE의 DeepSeek 토큰은 실행 최소분만 남는다. 상세: `docs/proposal/
forge-mcp-agent-runtime.md`, `token-cost-reduction.md`.

## 표본 한계
각 task 1회(N=1) 측정이라 통계 신뢰엔 반복이 필요하다. 방향(대폭 절감)은 명확하나,
default 정책을 추가로 바꾸기 전에는 반복 측정으로 성공률 gate를 재확인한다.
