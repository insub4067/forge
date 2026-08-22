# FORGE Agent Loop

> 기준: 2026-08-22 `main`

FORGE는 단일 LLM 호출형 챗봇이 아니라 **Flash-first / Pro-on-demand** 반복 실행 Runtime이다.

## 역할 파이프라인

```text
User Goal
 ↓
Triage Flash
 ├─ CHAT → Chat Flash → Done
 └─ AGENT SIMPLE/COMPLEX
          ↓
       Planner
          ↓
       Coder
          ↓
   ┌─ Reviewer ───────────────┐
   │      ↓                   │
   │  all tasks done? → Done  │
   │      ↓ no                │
   │   Debugger               │
   │      ↓                   │
   └── Re-review (최대 3회) ──┘
```

## Model Policy

| Role | 기본 | Thinking | 승격 |
|---|---|---|---|
| Triage | `deepseek-v4-flash` | off | 없음 |
| Planner | `deepseek-v4-flash` | on / medium | COMPLEX → `deepseek-v4-pro` / high |
| Coder | `deepseek-v4-flash` | off / low | 없음 |
| Reviewer | `deepseek-v4-flash` | on / medium | 없음 |
| Debugger | `deepseek-v4-flash` | off / low | 마지막 반복 복구에서 Pro / high |
| Chat | `deepseek-v4-flash` | off | 없음 |
| Vision | `deepseek-v4-flash-vision-exp` | off | 없음 |

Planner를 Pro 기본으로 사용하지 않는다. 비용 최적화의 기본 정책은 **Flash 우선, 실제 복잡도·실패 시에만 Pro**다.

## Task authority

Reviewer 텍스트가 성공을 의미하지 않는다. DB task가 모두 `done`일 때만 전체 성공이다.

주요 상태:

```text
todo → planning → in_progress → review → done
                                   ↓
                                 debug
                                   ↓
                                 review
```

## Tool Loop

각 role은 최대 step 내에서 다음을 반복한다.

```text
Model Call
→ tool calls
→ permission/approval
→ execute
→ observe/prune
→ 다음 Model Call
```

동일 tool+args 3회 연속 반복은 중단한다. 읽기 전용 `read_file/list_dir/grep`는 한 model 응답에 여러 개 있으면 병렬 prefetch한다.

## Runtime steering / concurrency

- 실행 중 새 사용자 메시지는 동일 세션 run을 새로 겹쳐 실행하지 않고 기존 run에 주입한다.
- `try_begin` 가드가 동일 session의 동시 run을 막는다.
- cancel은 실행 플래그뿐 아니라 대기 중 approval/question future도 해제한다.

## Context loop

1. provider가 반환한 `prompt_tokens`를 실제 입력 context로 본다.
2. 75% 초과 시 비파괴 compaction을 시도한다.
3. 오래된 surface를 Flash 요약으로 대체하고 원본 DB/history는 보존한다.
4. compaction 성공 시 압축 전 usage로 즉시 95% block하지 않는다.
5. 다음 model call에서 실제 줄어든 prompt size를 재측정한다.
6. 95% 초과 + 더 줄일 수 없는 경우 `context_blocked`로 종료한다.

긴 tool result는 model context에서 앞/뒤/오류 중심으로 축약한다. UI 및 저장 원본은 유지한다.

## Prompt cache

stable prefix는 `BASE_PROMPT + role instructions`이며 memory/skills는 뒤에 붙인다. role 시작 이벤트에 prefix hash가 포함되고 DeepSeek usage의 cache hit/miss를 별도로 기록한다.

Skill은 전량 삽입하지 않고 요청과 관련된 상위 최대 3개, 총 6000자 budget 내에서만 넣는다.

## Provider recovery

- reasoning_content 400 계열 → reasoning 제거, thinking off로 재시도
- 429/5xx/timeout/connection → 1/2/4초 backoff, 최대 3회
- 이미 stream delta가 발생한 뒤의 failure는 중복 출력 위험 때문에 자동 재시도하지 않는다.

## 종료 상태

| status | 의미 |
|---|---|
| `completed` | 정상 완료 |
| `review_limit` | 자기수정 3회 한도 초과 |
| `cancelled` | 사용자 중단 |
| `context_blocked` | context hard limit |
| `max_steps` | role step 한도 초과 |
| `repeated_tool_call` | 동일 도구 반복 |
| `failed` | 기타 실패 |

## Live status / durability

각 이벤트는 JSONL event log에 기록된다. 별도 `/status` API는 현재 role/activity/승인·질문 대기 상태를 제공해 SSE가 끊겨도 PWA가 polling으로 진행 상황을 복구한다.

서버 재시작 시 `sessions.running` 잔여 상태를 감지해 중단 안내를 남기지만 **실행 stack을 이어서 resume하지는 않는다.**

## 효율 평가

각 role의 token, cache hit/miss, model/tool calls, retry, compaction, elapsed time을 `agent_runs`에 기록한다. 최종 최적화 기준은 **cost per successfully completed task**다.
