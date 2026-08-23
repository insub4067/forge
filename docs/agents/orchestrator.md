# Agent Orchestrator

## 역할

실행 역할은 **Developer**(코드) 하나이고, 앞단에 최저가 라우터 Triage와 단순 대화용 Chat이
있다. Planner·Reviewer·Debugger는 두지 않는다 — Developer가 설계·구현·검증·수정을 한
컨텍스트에서 처리한다.

## 흐름

```
Triage (flash 최저가: chat vs code)
 ├─ CHAT → Chat (flash no-think 최저가) — 단순 대화
 └─ CODE → Developer
             Plan(3줄) → Execute → Verify → PASS: 완료
                                    └ FAIL: Diagnose → Repair → Verify
             막히면 pro+think-high로 승격(최대 2회 루프)
```

기본 flash+think-medium(Jr). 막힘(max_steps/repeated)일 때만 pro+think-high로 승격하고,
최대 2회까지 재시도(루프)한다. 그래도 못 풀면 남은 문제를 사용자에게 보고한다.

## 종료 조건

- Developer 자체검증 통과(완료)
- 승격 재시도 상한(2회) 초과 → 남은 문제 보고
- 최대 스텝 초과 / 컨텍스트 한도 / 사용자 중단
