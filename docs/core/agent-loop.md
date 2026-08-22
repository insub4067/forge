# FORGE Agent Loop

> 기준: 2026-08-23 `main`

FORGE는 단일 LLM 호출형 챗봇이 아니라 **Flash-first / Pro-on-demand** 반복 실행 Runtime이다.

## 역할 파이프라인

```text
User Goal
 ↓
Triage Flash
 ├─ CHAT → Chat Flash → Done
 ├─ AGENT SIMPLE → Coder → Reviewer → Done/Debugger
 └─ AGENT COMPLEX → Planner → Coder → Reviewer → Done/Debugger
```

SIMPLE 작업은 Planner를 생략한다. Planner가 짧은 작업에서도 전체 context를 다시 읽으며 큰 토큰 비용을 만들던 실측 병목을 제거하기 위한 정책이다. Reviewer는 SIMPLE에서도 반드시 실행된다.

COMPLEX 작업만 Planner를 사용하며, 상세 분해가 필요한 경우 품질을 보존한다.

## Model Policy

| Role | 기본 | Thinking | 실행 조건/승격 |
|---|---|---|---|
| Triage | `deepseek-v4-flash` | off | 없음 |
| Planner | Flash/Pro routing | on | **COMPLEX에서만 실행** |
| Coder | `deepseek-v4-flash` | off / low | 없음 |
| Reviewer | `deepseek-v4-flash` | on / medium | 없음 |
| Debugger | `deepseek-v4-flash` | off / low | 마지막 반복 복구에서 Pro / high |
| Chat | `deepseek-v4-flash` | off | 없음 |
| Vision | `deepseek-v4-flash-vision-exp` | off | 없음 |

비용 최적화 기본 정책은 **불필요한 role 자체를 실행하지 않고, Flash 우선·실제 복잡도와 실패에만 더 비싼 추론을 사용**하는 것이다.

## Task authority

Reviewer 텍스트가 성공을 의미하지 않는다. DB task가 모두 `done`일 때만 전체 성공이다.

```text
todo → planning → in_progress → review → done
                                   ↓
                                 debug
                                   ↓
                                 review
```

## Tool Loop

각 role은 최대 step 내에서 `Model Call → tool calls → approval → execute → observe/prune → 다음 Model Call`을 반복한다.

동일 tool+args 3회 연속 반복은 중단한다. 읽기 전용 `read_file/list_dir/grep`는 한 model 응답에 여러 개 있으면 병렬 prefetch한다.

FORGE 자체 프론트 개발에는 `build_frontend` 도구가 추가됐다. sandbox에 Node가 없어도 host에서 `npm run build`를 실행해 소스 수정 → production build 검증/반영까지 Agent가 닫을 수 있다. `frontend/dist/**`는 직접 수정하지 않는다.

## Runtime steering / concurrency

- 실행 중 새 사용자 메시지는 기존 run에 주입한다.
- `try_begin` 가드가 동일 session 동시 run을 막는다.
- cancel은 대기 중 approval/question future도 해제한다.
- PWA 재접속 시 `/status`의 pending 상태로 승인 UI를 복구할 수 있다.

## Context loop

1. provider의 `prompt_tokens`를 실제 입력 context로 본다.
2. 75% 초과 시 비파괴 compaction을 시도한다.
3. 오래된 surface를 Flash 요약으로 대체하고 원본 DB/history는 보존한다.
4. compaction 성공 직후 압축 전 usage로 95% block하지 않는다.
5. 다음 model call에서 실제 prompt size를 재측정한다.
6. 95% 초과 + 더 줄일 수 없으면 `context_blocked`로 종료한다.

긴 tool result는 model context에서 앞/뒤/오류 중심으로 축약하며 저장 원본은 유지한다.

## Prompt cache / Skills

stable prefix는 `BASE_PROMPT + role instructions`이며 memory/skills는 뒤에 붙인다. DeepSeek usage의 cache hit/miss를 별도 기록한다.

Skill은 요청과 관련된 상위 최대 3개, 총 6000자 budget 내에서만 넣는다.

## Provider recovery

- reasoning_content 400 계열 → reasoning 제거 + thinking off recovery
- 해당 오류를 한 번 겪은 session은 이후 call부터 thinking을 미리 꺼 반복적인 `400 → retry` 낭비를 방지
- 429/5xx/timeout/connection → 1/2/4초 backoff, 최대 3회
- stream delta 발생 뒤 failure는 중복 출력 위험 때문에 자동 retry하지 않음

## 종료 상태

| status | 의미 |
|---|---|
| `completed` | 정상 완료 |
| `review_limit` | 자기수정 한도 초과 |
| `cancelled` | 사용자 중단 |
| `context_blocked` | context hard limit |
| `max_steps` | role step 한도 초과 |
| `repeated_tool_call` | 동일 도구 반복 |
| `failed` | 기타 실패 |

## Live status / durability

각 이벤트는 JSONL event log에 기록된다. `/status` API는 role/activity/승인·질문 대기 상태를 제공해 SSE가 끊겨도 PWA가 polling으로 복구한다.

서버 재시작 시 중단된 run을 감지·정리하지만 **실행 stack을 이어서 resume하는 durable worker는 아직 구현되지 않았다.**

## 효율 평가

각 role의 token, cache hit/miss, model/tool calls, retry, compaction, elapsed time을 `agent_runs`에 기록한다. 최상위 최적화 기준은 **cost per successfully completed task**다.
