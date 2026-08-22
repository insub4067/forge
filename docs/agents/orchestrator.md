# Agent Orchestrator

## 역할

역할별 에이전트(Planner, Coder, Reviewer, Debugger)를 조율하는 실행 관리자.

## 태스크 상태 전이

```
todo
  ↓ Planner가 계획을 등록
planning
  ↓ Coder가 작업 시작
in_progress
  ↓ 구현 완료
review       ← Reviewer 검토
  ↓ 통과             ↓ 실패
done              debug
                     ↓ Debugger 수정 완료
                   review (재검토)
```

## 흐름

1. **Planner** — 요구 분석 → 태스크 분해 → `update_tasks`
2. **Coder** — 태스크를 `in_progress`로 바꾸고 구현 → `review`로 전환
3. **Reviewer** — 검토·검증 → 통과 시 `done`, 실패 시 `debug`
4. **Debugger** — 원인 분석·수정 → `review`로 되돌림
5. 모든 태스크가 `done`이면 종료 보고

## 종료 조건

- 모든 태스크 `done`
- 최대 스텝 초과
- 컨텍스트 한도 도달
- 사용자 중단
