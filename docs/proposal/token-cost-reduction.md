# FORGE 토큰 비용 절감 전략

> 상태: Living doc (실측 기반, 계속 갱신)
> 북극성: **성공률을 유지하면서 성공 작업당 DeepSeek 토큰 비용을 획기적으로 줄인다.**
> 판정: 모든 후보는 `bench.py`(R0) + `rsi.py` promotion_gate로 검증 — 성공률 후퇴 시 탈락.

## 실측된 비용 구조 (2026-08-23)

role별 실제 달러 비중(캐시 단가 반영): **planner 73%**, coder 13%, reviewer 8%, chat 6%.
planner 토큰의 93.6%가 단일 마라톤 세션에서 나왔다. 즉 비용의 핵심은 **planner(추론) +
긴 세션 히스토리 재전송**이다. 코딩·리뷰 자체는 싸다.

## 레버 (측정치 순)

### L1. 추론/실행 분리 — 외부(MCP 호출부)가 계획, FORGE는 코딩만 ★최대
- 구현됨: `forge_execute(goal, workspace, plan?)`. plan 제공 시 세션별 planner-off.
- **실측(COMPLEX task C, 1회)**: 내부 planner(PRO) $0.00526 → 외부계획+planner off **$0.00180 (약 −66%)**, 성공 유지, planner_tok=0.
- 근거: planner가 비용 73%. ChatGPT 등 정액 무제한 모델이 추론을 맡으면 그 비용은 사실상 0이 되고, FORGE는 Coder+Reviewer 토큰만 쓴다.
- 남은 검증: No-Planner variant 벤치(5 COMPLEX×2)로 성공률 하락 폭 확인. 외부계획 경로는 계획 도움이 있어 bare No-Planner보다 성공률이 높을 것(상한).

### L2. planner flash (COMPLEX에서 pro 대신 flash)
- 상태(2026-08-24 정정): `FORGE_PLANNER_FLASH` 플래그는 코드에 없다(제거됨). 현재 planner 역할은
  기본이 flash+think-medium이라 플래그 없이도 flash로 돈다(`model_router.py`). 아래 실측은 옛 플래그 기준 기록.
- **실측(COMPLEX 5×2)**: pro $0.00592 → flash **$0.00480 (−19%)**, 성공 3/3 유지(표본 작음).
- L1이 적용되면 무의미(planner 자체가 없음). L1을 못 쓰는 전체위임 경로의 차선책.

### L3. 세션 수명 관리 — 작업마다 새 세션
- 비용 폭주의 93.6%가 마라톤 세션의 히스토리 재전송. 무위험(코드 변경 0).
- 작업 단위로 세션을 나누면 per-call 컨텍스트가 작아져 모든 role 비용이 하락.
- MCP facade는 task마다 새 세션을 만든다 → 이미 이 원칙을 따름.

### L4. 컨텍스트 압축 임계 조정 (미검증)
- 현재 `logical_budget=262144`. 긴 세션에서 압축이 늦게 걸린다.
- 낮추면 planner/coder 컨텍스트↓ 이나 압축은 lossy → 성공률 위험. R0로 A/B 후에만.

### L5. skill 주입 효과 (미검증)
- `FORGE_SKILLS_OFF=1`로 skill on/off A/B. skill이 성공률을 안 올리면서 토큰만 늘리면 축소.
- 현재 skill은 ≤6000자·선택적이라 비용 영향은 작음. 우선순위 낮음.

## 실행 원칙

1. **L1이 압도적.** 외부 오케스트레이터(Claude/ChatGPT via MCP)가 계획하고 FORGE는 코딩만 하는
   구조를 기본 사용 경로로 만든다. planner는 "호출부가 계획을 안 줄 때만" 도는 fallback.
2. 모든 변경은 성공률 gate 통과가 필수. 비용만 낮추고 성공률이 떨어지면 폐기.
3. 표본이 작으면 결론을 미룬다. COMPLEX benchmark를 늘려 신뢰도를 확보한다.

## 다음
- No-Planner / plan-provided 경로의 성공률을 COMPLEX benchmark로 통계화(현재 N=1~2).
- L1을 REST(`/api/chat`)에도 노출할지 검토(외부 오케스트레이션이 아니어도 계획 주입 가능).
- task R처럼 review/debug 루프가 폭주하는 유형(621s) 별도 분석 — elapsed·비용 outlier.
