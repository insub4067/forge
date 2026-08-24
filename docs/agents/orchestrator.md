# Agent Orchestration Policy

## 현재 흐름

FORGE는 role을 많이 두는 것이 목적이 아니다. **Developer가 유일한 mutation executor**이고, 필요한 경우에만 가벼운 Planner/Reviewer를 붙인다.

```text
Room mode
├─ chat → Chat(read-only)
├─ work → coding path
└─ auto → Triage(chat/work)

coding path
├─ simple  → Developer
└─ complex → Planner(read-only, fresh)
             → Developer
             → Reviewer(fresh, independent)
                 └ FAIL → Developer repair 1회
```

`multi/single` 강제 선택 규칙은 Runtime에 일부 남아 있지만 현재 API/UI에는 배선돼 있지 않다. 사용자는 orchestration topology를 관리하지 않고 FORGE가 자동 판정한다.

## Model policy

- Chat/Triage: Flash 계열
- Planner: Flash + 제한된 step/context
- Developer: Flash-first. `auto`에서는 반복 막힘(max_steps/repeated) 시 Pro로 bounded escalation한다.
- 세션 tier `pro`: Developer를 처음부터 Pro + high reasoning으로 실행한다.
- 세션 tier `flash`: Pro escalation 없이 Flash 경로를 유지한다.
- Reviewer: Flash 기반 독립 검토
- Gate Recovery: Flash, 최대 3 step, `update_gates`만 허용

## Completion authority

Role의 자연어 판정은 최종 authority가 아니다.

```text
Developer done
→ gate coverage 확인/recovery
→ generic test/build
→ acceptance gate 실행
→ integration verification
→ process-owned CompletionSummary
```

`completed`는 프로세스 검증이 허용한 상태에서만 나온다. `completed_unverified`, `verification_failed`, `cancelled`, `budget_exceeded`, `context_blocked` 등은 별도 종료 상태다.

## Boundaries

- Planner/Reviewer 파생 context는 `persist=False`; 세션 전체 history를 덮지 않는다.
- Reviewer FAIL → Developer 수리는 최대 1회다.
- Developer escalation도 bounded다.
- 동일 tool 반복, cost budget, context budget, cancellation이 runaway를 제한한다.
