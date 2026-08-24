# FORGE Database Schema

> SQLAlchemy model(`backend/app/db/models.py`) 기준 요약. `create_all` + idempotent column patches를 사용한다.

## sessions

Room/task의 durable state.

주요 필드:

- `id`, `title`, `workspace_id`, `workspace_path`, `workspace_locked`
- `mode`: `""` auto | `chat` | `work`
- `status`
- `logical_budget`, `used_tokens`
- `running`, `final_status`
- `auto_approve`
- `model_tier`: `auto | flash | pro`
- `compact_summary`, `compact_covered`
- `created_at`, `archived_at`

`running/final_status/history`는 restart detection/resume의 근거다. `auto_approve/model_tier`는 재시작 후에도 같은 capability/model policy를 복원한다.

## messages

세션 history.

- `id`, `session_id`, `seq`
- `role`, `content_json`
- prompt/completion/cached token fields

Process-owned 최종 CompletionSummary도 assistant history에 영속된다.

## tasks

Kanban.

- `title`, `status`, `progress`
- 정상 상태: `todo → working → testing → done`

모델은 todo/working까지만 직접 설정하고 testing/done은 process verification이 소유한다.

## acceptance_gates

사용자 요구사항 ledger.

- `title`, `description`
- `verification_method`, `expected_result`
- `status`: pending | working | passed | failed | unavailable | blocked | abandoned
- `evidence`, `failure_reason`

`passed/failed`는 process가 실제 command 실행 뒤에만 쓴다. Evidence에는 command/exit/output/expected가 기록된다. Gate update는 기존 requirement를 조용히 삭제하지 않도록 merge/ledger invariants를 사용한다.

## checkpoints

mutation 전 Git SHA/step checkpoint.

- `session_id`, `git_sha`, `step_no`, `created_at`

## agent_runs

role/model 실행 telemetry.

- model/thinking/reasoning
- prompt/completion/cache hit/miss tokens
- model/tool calls, retries, compactions, elapsed
- selected skills
- tool raw/visible token estimates

비용 계산과 benchmark/병목 분석에 사용한다.

## push_devices

Web Push subscription metadata.

- name, endpoint, subscription JSON, last_seen

## scheduled_jobs

시간 기반 automation.

- name, prompt, workspace/session
- timezone
- `next_run_at`(naive UTC stored; scheduler authority)
- recurrence: `"" | daily | interval`
- recurrence_value
- auto_approve, enabled, status
- last_run_at/result
- retries/max_retries

현재 별도 `job_runs` table은 없다. run 결과는 session/history/agent_runs와 scheduled_jobs의 last fields를 재사용한다.

## refinements

반복 failure evidence에서 만든 개선 후보.

- type: skill | supplement
- scope: project | global
- target / proposed_change
- before_text / after_text
- evidence_runs / evidence_json / failure_pattern
- expected_effect
- status: pending | approved | ignored
- decided_at

승인 시 Project/Learned skill 파일에 적용할 수 있고 rollback은 before_text를 사용한다. 자동 main/prompt mutation은 아니다.

## 파일 기반 durable state

DB 외에도 의도적으로 파일을 사용한다.

- `ROOM_MEMORY.md`: provenance/evidence validation을 통과한 프로젝트 사실
- `GLOBAL_MEMORY.md`: 모든 room 공통 보조 규칙
- `.forge/skills/*.md`: curated/project skill
- `~/.forge/skills/*.md`: global/learned skill
- JSONL event/error/tool-result logs

## 현재 없는 schema

- durable worker queue/run_state event-sourcing table
- condition watcher state table
- generic provider/model profile table
- parallel worker/worktree ownership table

이들은 proposal이며 현재 schema로 가정하지 않는다.
