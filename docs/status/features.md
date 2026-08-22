# FORGE — 기능 목록

> 기준: 2026-08-22 `main`

## Agent Runtime

| 기능 | 상태 |
|---|---|
| Triage CHAT / AGENT 분기 | ✅ |
| AGENT SIMPLE / COMPLEX 난이도 판정 | ✅ |
| Planner Flash 기본 / COMPLEX Pro 승격 | ✅ |
| Coder Flash | ✅ |
| Reviewer ↔ Debugger 자기수정 루프 | ✅ |
| Debugger 마지막 복구 Pro 승격 | ✅ |
| 최대 step / review cycle 제한 | ✅ |
| 동일 tool 반복 감지 | ✅ |
| 동일 session 동시 run 가드 | ✅ |
| 실행 중 메시지 injection | ✅ |
| cancel | ✅ |

## Context / 비용 효율

| 기능 | 상태 |
|---|---|
| provider 실측 prompt token 기반 pressure | ✅ |
| Tool result model-free pruning | ✅ |
| 75% 비파괴 context compaction | ✅ |
| compaction 후 다음 호출 재측정 | ✅ |
| 95% hard block | ✅ |
| stable prefix hash | ✅ |
| DeepSeek cache hit/miss telemetry | ✅ |
| selective Skill retrieval | ✅ |
| read-only tool 병렬 prefetch | ✅ |
| role/session metrics 집계 | ✅ |
| estimated cost 계산(가격 설정 시) | ✅ |
| bottleneck diagnostic rule | ✅ |
| Tool Script/RPC Mode | ⬜ |

## Provider Recovery

- reasoning_content 오류 → reasoning 제거 + thinking off 재시도 ✅
- 429/5xx/timeout/connection 1/2/4초 backoff ✅
- 이미 stream output이 발생한 뒤의 자동 retry 금지 ✅

## Tool / Execution

| Tool | 상태 | 승인 |
|---|---|---|
| read_file | ✅ | 자동 |
| list_dir | ✅ | 자동 |
| grep | ✅ | 자동 |
| write_file | ✅ | 필요 |
| edit_file | ✅ | 필요 |
| bash | ✅ | 필요 |
| ask_user | ✅ | - |
| update_tasks | ✅ | - |
| save_skill | ✅ | 필요 |

- Docker Sandbox 기본 실행 ✅
- `SANDBOX_MODE=host` 옵트인 host 실행 ✅
- `/workspace` 경로를 실제 workspace로 치환하는 host 실행 지원 ✅
- mutation 전 git SHA checkpoint ✅
- write/edit unified diff ✅

host 모드는 격리를 우회하므로 신뢰된 개인 환경에서만 사용한다.

## Session / Persistence

- PostgreSQL 세션·메시지·task·checkpoint 영속화 ✅
- agent_runs token/cache/model/tool/retry/compaction/elapsed 계측 ✅
- `sessions.final_status` / `sessions.running` ✅
- 서버 시작 시 interrupted run reconcile ✅
- run crash 오류 메시지 히스토리 저장 ✅
- Session search ✅
- JSONL durable event/action log ✅
- 서버 재시작 후 실제 실행 resume ⬜
- Redis Streams event replay ⬜

## Remote / PWA

- 모바일 채팅/세션 드로어 ✅
- workspace 필수 선택 ✅
- 승인/질문 UI ✅
- 승인·질문 600초 timeout ✅
- `/status` running/role/activity/waiting 상태 polling ✅
- SSE가 끊긴 동안 현재 활동 표시 ✅
- 실행 중 칸반 live refresh ✅
- task 상태 전이 인라인 표시 ✅
- Git changes/history/branch/diff ✅
- workspace 경계 제한 파일 브라우저 ✅
- Skills 확인/삭제 + collapsible 카드 ✅
- 세션 context/cache/efficiency metrics ✅
- 첨부 이미지 썸네일 + 전체화면 이미지 뷰어 ✅
- 4종 테마 + FORGE 로고/PWA 이름 ✅
- iOS safe-area ✅
- history loading skeleton ✅
- PWA 업데이트 무한 reload 방지 ✅
- Web Push ⬜

## Security / Guard

- write/edit/bash/save_skill approval ✅
- Docker Sandbox non-root/resource limit ✅
- host 실행은 명시적 옵트인만 허용 ✅
- session workspace 밖 `/fs/list`, `/fs/read` 접근 차단 ✅
- cancel 시 pending approval/question 해제 ✅
- event/action durable log ✅

## 향후

1. durable worker + 실제 resume/event replay
2. Tool Script/RPC Mode
3. Scheduled / Condition Jobs + Web Push
4. ExecutionBackend(Local/SSH/Docker)
5. isolated subagents

Multi-Agent, MCP, Vector Search는 실제 성능 병목/사용 요구가 확인된 뒤 도입한다.
