# FORGE Improvement Plan

> 단기 실행용. Current State는 `../status/work-status.md`, 큰 방향은 `roadmap-priority.md`가 authority다.

## 목표

기능을 더 많이 넣는 대신 **Claude처럼 계속 쓰고 싶은 daily-use agent**에 가까워지게 한다.

## 1. Reliability Probe Pack

실제 repository 작업을 반복해 다음을 기록한다.

- 요구사항 수 vs gate 수
- gate가 external deterministic checker를 실제로 대표하는지
- `gated / recovered_gated / generic_only`
- verification failure → repair 성공률
- `completed_unverified` 원인
- ask_user/approval/steering 횟수
- final report가 실제 evidence와 일치하는지

약한 gate/거짓 gate/불필요한 질문이 반복되면 해당 failure mode만 좁게 수정한다.

## 2. Startup Reliability

`main.py` lifespan이 DB create/migration/resume setup 예외를 broad하게 삼키는 부분을 점검한다.

목표:

- schema migration 실패는 로그/health에서 명확히 보임
- resume 한 세션 실패가 전체 startup을 죽이지 않음
- 예상 가능한 per-session failure와 fatal schema failure를 구분

## 3. Provider Boundary

DeepSeek baseline을 고정하고 OpenAI-compatible adapter 하나만 추가하는 작은 실험을 한다.

- AgentRuntime/verification은 provider를 모름
- tool calling/usage/cache/thinking capability 차이를 adapter가 흡수
- 동일 25-task benchmark + 실제 repo probe
- 성공률 후퇴 시 route에 넣지 않음

Ling/OpenRouter는 과거 실사용 실패가 있으므로 “싸다”만으로 다시 기본 후보로 넣지 않는다.

## 4. Automation / Worker Semantics

Scheduled Jobs는 이미 있다. 다음은 Condition/Deferred와 crash ownership이다.

작은 순서:

1. deterministic Condition interface
2. persisted condition state/idempotency
3. trigger true일 때만 기존 AgentRuntime 호출
4. independent worker가 필요한 failure case를 실제로 재현한 뒤 process split 검토

## 5. Context / Memory Monitoring

Compaction persistence와 evidence-bound Project Memory가 막 들어간 상태이므로 새 구조를 더 얹기 전에 관찰한다.

- compact hit 이후 다음 run input 감소 확인
- stale/invalid compact summary 복원 방지
- memory candidate saved/rejected 이유 분포
- ROOM_MEMORY가 source와 충돌하지 않는지 정기 probe
- 4KB cap 도달 시에만 memory GC/selective retrieval 검토

## 6. UX 원칙

- 실행 상태는 activity card 한 곳
- task 진행은 task-bar 한 곳
- 최종 보고는 짧고 process-owned
- debug token/tool/raw evidence는 필요할 때만 상세 화면
- orchestration mode를 사용자에게 떠넘기지 않음

## 완료 기준

다음이 실제로 개선될 때만 이 계획이 성공이다.

- verified task success 유지/향상
- false completion 감소
- human interventions/task 감소
- 같은 문제를 재설명하는 횟수 감소
- cost/elapsed는 위 조건을 지킨 뒤 감소
