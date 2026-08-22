# FORGE — 데이터베이스 스키마

> PostgreSQL · 기준: 2026-08-22 `main`

## 주요 테이블

| 테이블 | 용도 |
|---|---|
| `sessions` | 채팅방/워크스페이스 및 run 상태 |
| `messages` | 대화 원본 기록 |
| `tasks` | Agent task/칸반 상태 |
| `checkpoints` | mutation 전 git SHA |
| `agent_runs` | role별 모델·토큰·효율 telemetry |

실행 이벤트 자체는 별도 JSONL event/action log에도 기록된다.

## sessions

주요 필드:

- `id` — session UUID
- `title`
- `workspace_id` — 레거시 식별자
- `workspace_path` — 실제 로컬 프로젝트 경로
- `status`
- `model`
- `logical_budget`
- `used_tokens` — 최근 실측 context usage
- `running` — 현재 run 실행 중 여부
- `final_status` — 마지막 run 종료 상태
- `created_at`, `archived_at`

`workspace_path`는 파일 브라우저 및 Agent 실행 경계의 기준이다. 신규 세션은 workspace 선택이 필수다.

### final_status

대표 값:

```text
completed
review_limit
cancelled
context_blocked
max_steps
repeated_tool_call
failed
```

성공률 집계의 기본 성공 정의는 `final_status == completed`다.

## messages

대화 원본을 저장한다. model context compaction/pruning은 이 원본을 파괴하지 않는다.

주요 필드:

- `id`
- `session_id`
- `seq`
- `role`
- `content_json`
- token 관련 legacy/집계 필드

`content_json`에는 일반 text뿐 아니라 필요 시 tool call, reasoning 등 provider-neutral message 정보를 포함한다.

## tasks

상태 기반 Reviewer/Debugger 루프의 authority.

```text
todo → planning → in_progress → review → done
                                   ↓
                                 debug
                                   ↓
                                 review
```

주요 필드:

- `id`
- `session_id`
- `title`
- `status`
- `progress`
- `created_at`, `updated_at`

Reviewer는 미완료 task를 `debug` 또는 `done`으로 판단하고 Debugger는 수정 후 `review`로 되돌린다.

## checkpoints

`write_file`, `edit_file`, `bash`, `save_skill` 등 승인/mutation 경계에서 현재 git SHA를 저장한다.

주요 필드:

- `id`
- `session_id`
- `git_sha`
- `step_no`
- `created_at`

현재 checkpoint는 audit/rollback 기준점을 제공하지만 자동 rollback 엔진은 아니다.

## agent_runs

역할별 실행 비용과 성능을 기록한다. 스키마 변화는 기존 DB에 idempotent ALTER 방식으로 보강한다.

주요 데이터:

- `session_id`
- `role`
- `model`
- `thinking`
- `reasoning_effort`
- `prompt_tokens`
- `completion_tokens`
- `cache_hit_tokens`
- `cache_miss_tokens`
- `model_calls`
- `tool_calls`
- `retries`
- `compactions`
- `elapsed_ms`
- selected Skill 정보

이를 기반으로 다음 집계를 계산한다.

- success rate
- average tokens per success
- cache hit ratio
- Pro escalation rate
- review first-pass rate
- debugger activation rate
- model/tool call count
- estimated cost(모델 가격 설정이 있을 때)

API:

- `GET /api/metrics/summary`
- `GET /api/rooms/{id}/metrics`

## Run persistence

run 시작 시 `sessions.running=true`, 정상/비정상 종료 시 false로 정리한다. 프로세스가 재시작되며 true가 남은 경우 startup reconcile이 해당 run을 중단된 것으로 표시하고 히스토리에 복구 안내를 남긴다.

이는 **실행 continuation 저장**이 아니다. model/tool stack과 pending executor 상태를 복원하는 durable resume은 향후 worker/event replay 단계다.

## Event log

AgentRuntime의 `send()` 이벤트는 JSONL durable log에 기록한다. 현재 이 로그는 감사/문제 추적 목적이며 PostgreSQL message history와 역할이 다르다.

향후 Redis Streams 또는 동등한 durable queue를 authoritative execution event replay 계층으로 사용할 수 있으나 현재는 미구현이다.

## 데이터 원칙

- 저장 원본과 모델 context projection 분리
- cache hit과 miss를 별도 저장
- 누적 API 비용과 현재 context pressure를 혼동하지 않음
- telemetry는 최적화 판단용이며 핵심 기준은 `cost per successfully completed task`
