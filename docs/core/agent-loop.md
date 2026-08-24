# FORGE Agent Loop

> 현재 Runtime 기준. Proposal이 아니라 실제 동작 설명이다.

## 1. Routing

Room은 `mode`를 가진다.

- `chat`: 읽기 전용 Chat. mutation은 거부한다.
- `work`: Triage 없이 바로 coding path.
- `""`(auto): Triage가 chat/work를 분류한다.

Chat으로 오분류됐는데 mutation tool을 시도하면 Runtime이 이를 감지해 work 전환 신호를 낸다.

## 2. Coding topology

현재 사용자-facing agent mode는 auto다.

```text
simple  → Developer
complex → Planner → Developer → Reviewer
                           FAIL → Developer repair 1회
```

복잡도는 요청 길이/키워드/멀티턴 등의 deterministic heuristic으로 판단한다. Planner는 read-only fresh context, Reviewer는 Developer의 긴 tool history를 상속하지 않는 fresh/minimal context를 사용한다. 둘 다 `persist=False`라 파생 context가 세션 history를 덮지 않는다.

상위 MCP 호출자가 `plan`을 제공하면 그 계획을 user content에 포함해 내부 계획 비용을 줄이는 경로가 있다.

## 3. Developer model loop

- 기본 Flash + thinking.
- `auto`: max_steps/repeated 등 막힘 신호에서 Pro로 bounded escalation.
- `pro`: 처음부터 Pro/high.
- `flash`: Flash 유지.
- Developer 최대 step은 60, escalation은 최대 2회다.
- 동일 tool+arguments 3회 연속이면 repeated-tool guard로 중단한다.
- 읽기 전용 tool call이 한 응답에 여러 개면 I/O를 병렬 prefetch한다.

## 4. Requirement registration

Developer는 구현 전에 사용자 요구사항을 Acceptance Gate Ledger로 등록한다. 구현 후 실제 파일 변경이 있는데 gate가 0개면 `gate_recovery`가 1회 실행된다.

Gate Recovery:

- Flash
- 최대 3 step
- `update_gates`만 제공
- 코드 탐색/수정/명령 실행 불가
- 실패해도 main task 자체를 crash시키지 않음

여전히 gate가 없으면 fully verified completion을 금지한다.

## 5. Verification pipeline

```text
implementation
→ Generic Verification
→ Acceptance Gate Verification
→ Integration Verification
→ Completion
```

### Generic

현재 흔한 구조만 자동 검출한다.

- root/frontend `package.json`의 build script
- root/backend `test_*.py` + pytest
- FORGE self-repo면 Playwright runtime smoke

상태는 `passed / failed / unavailable`. pytest exit 1은 test failure, exit 2/3/4/5나 실행 불가는 unavailable로 구분한다.

### Acceptance

Gate command는 `DockerSandbox.run_verify()` 경계를 통해 실행한다. PASS는 `exit 0`이면서 `expected_result`가 stdout에 실제로 존재할 때만 가능하다. command/exit/output/expected를 evidence로 저장한다.

### Integration

Gate가 있는 작업은 최종 workspace에 generic verification을 다시 실행하고 남은 failed gate가 없는지 확인한다.

## 6. Repair

Generic failure는 Developer에 실제 실패 로그를 주고 1회 bounded repair한다. Acceptance gate failure도 실제 gate 결과를 주고 Developer에 한 번 수리를 맡긴다. 무한 review/repair loop는 만들지 않는다.

## 7. Completion policy

- `completed`: fully verified path. task finalize, auto commit/push 가능.
- `completed_unverified`: 일부/전체 verification unavailable 또는 gate coverage 부족. local commit은 가능하지만 auto push 금지.
- `verification_failed`: 검증 실패. commit/push 금지.
- `cancelled`, `context_blocked`, `budget_exceeded`, `repeated_tool_call`, `max_steps` 등은 별도 실패/중단 상태.

최종 응답은 `CompletionSummary`를 deterministic formatter가 process-owned 사실로 만든다. 모델 자기서술은 authority가 아니다. 이 보고는 history에도 저장돼 새로고침 후 유지된다.

## 8. Context lifecycle

- logical budget: 131,072 tokens
- ~75%: 오래된 context를 summary로 compaction
- ~95%: hard block
- compaction `summary/covered`는 DB에 영속하고 다음 run에서 복원
- 큰 파일: symbol map → `find_symbol`
- 긴 tool result: prune → tool_store → 필요 시 `read_tool_result`
- selected Skills만 max count/char budget 안에서 삽입
- 새 task에서는 `새 세션 + 같은 workspace`로 long conversation과 project continuity를 분리할 수 있음

## 9. Memory / Learning

Project Memory는 completed 작업의 passed gates/verification evidence에서 candidate `{fact, source, evidence}`를 만들고 `memory_guard`가 source 존재, changed-file 관계, evidence, unsupported claim, duplicate 등을 검증한 뒤에만 `ROOM_MEMORY.md`에 저장한다. Memory는 보조 정보이며 현재 source가 우선한다.

Refinement는 반복된 실제 failure signature에서 후보를 만들고 사용자가 approve/ignore/rollback한다. 자동 prompt/main 수정은 하지 않는다.

## 10. Durability / Cancellation / Budget

- step history와 session state를 PostgreSQL에 저장한다.
- 서버 재시작 시 interrupted run을 history에서 headless resume한다.
- `resuming` 상태에서 다시 죽은 run은 재재개하지 않는다.
- persisted auto-approve/model-tier를 복원해 restart가 privilege/model policy를 확장하지 않게 한다.
- cancellation은 실행 중 tool task를 취소하고 하위 subprocess 정리를 시도한다.
- run cost를 누적해 세션 budget을 넘으면 `budget_exceeded`로 종료한다. `0`은 unlimited semantics다.
