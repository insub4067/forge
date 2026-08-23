# FORGE Agent Loop

> 기준: 2026-08-23 `main` (올인원 구조)

FORGE는 단일 LLM 호출형 챗봇이 아니라 **Flash-first / Pro-on-demand** 반복 실행 Runtime이다.
에이전트 수를 줄이는 것이 최고의 비용 절감이다 — 에이전트가 늘 때마다 그 역할이 컨텍스트를
처음부터 다시 읽는 input token 비용이 발생한다. 그래서 Planner/Reviewer/Debugger를 별도
역할로 두지 않고 **Developer 하나**가 설계·구현·검증·수정을 한 컨텍스트에서 처리한다.

## 역할 파이프라인 (2 roles)

```text
User
 ↓
Triage (flash, 최저가 라우터: chat vs code)
 ├─ CHAT → Chat (flash no-think, 최저가) — 단순 대화·인사·짧은 질문
 └─ CODE → Developer (flash + thinking medium)
             ↻ Plan(3줄) → Execute → Verify(테스트/빌드) → PASS: 완료
                                  └ FAIL: Diagnose → Repair → Verify
             ↓ 막히면 pro + think-high로 승격(최대 2회 루프)
(이미지가 있으면 Vision이 먼저 분석해 텍스트로 전달)
```

Developer는 execute→verify→repair를 **같은 컨텍스트에서** 돈다. 역할 전환에 따른 컨텍스트
재전송·별도 LLM 호출이 사라져 토큰·시간·API 호출이 준다. 무한 수정은
`DEVELOPER_MAX_STEPS`(45) + 반복 도구 호출 차단 + 승격 1회 상한으로 막는다.

외부(MCP 호출부)가 계획을 제공하면 그 계획을 Developer 컨텍스트에 실어 그대로 따른다
(별도 Planner 없음).

## Model Policy

| Role | 기본 | Thinking | 승격 |
|---|---|---|---|
| Triage | `deepseek-v4-flash` | off / low | 없음 (chat vs code 라우터) |
| Chat | `deepseek-v4-flash` | off / low | 없음 (단순 대화 최저가) |
| **Developer** | `deepseek-v4-flash` | **on / medium** | 막힘 시 pro + think-high로 승격(최대 2회 루프, Jr→Sr) |
| Vision | `deepseek-v4-flash-vision-exp` | off / low | 없음(이미지 전처리) |

핵심 전략(DeepSeek 권고): 무조건 pro를 쓰지 않는다. **기본 flash+think-medium으로 대부분을
한 번에 완성**하고, 실패할 때만 pro+think-high로 승격한다. 90% 비용을 아끼며 품질을 확보한다.
`FORGE_DEVELOPER_PRO=1`이면 항상 pro(실험용). 단순 대화는 최저가 flash Chat으로 빠지고, Developer는 코드 작업에만 flash+think를 쓴다.

## 완료 판정

Developer가 스스로 검증(테스트/빌드 실행)해 통과하면 완료한다. 세션 `final_status ==
"completed"`가 성공의 authoritative 정의다(telemetry 집계 기준).

## Telemetry

- `pro_escalation_rate` = Sr(pro) 승격이 일어난 세션 비율 = Developer가 flash로 자주 막히는지.
- `review_first_pass_rate` = 승격 없이 완료한 비율 = Developer 첫 패스 성공률.
- role·model·tokens·model_calls·tool_calls·retries·elapsed는 `agent_runs`에 그대로 기록.

## MCP External Planner

향후 상위 모델(GPT/Claude)이 계획을 담당하고 FORGE는 실행만 하는 구조:

```text
External Planner (GPT / Claude)  ← 무제한 chat, 추론 비용 사실상 0
        ↓ TaskSpec(goal, plan, constraints, acceptance_criteria)
Forge Developer
        ↓ Execute → Verify → Repair
```

`forge_execute(goal, workspace, plan)` — plan을 주면 Developer가 그 계획대로 실행한다.
