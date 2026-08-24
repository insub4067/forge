# FORGE Feature Matrix

> 2026-08-24 current source 기준. 날짜형 decision/handoff와 proposal의 과거 상태보다 이 문서와 source를 우선한다.

| 영역 | 상태 | 현재 구현 |
|---|---|---|
| Room routing | ✅ | `auto/chat/work`; auto는 Triage, work는 coding path 직행 |
| Chat | ✅ | read-only Chat + mutation 시 work 전환 신호 |
| Simple coding | ✅ | single Developer |
| Complex coding | ✅ | auto heuristic → fresh Planner → Developer → fresh Reviewer; FAIL 시 수리 1회 |
| User multi/single override | ⏸️ | 내부 규칙은 있으나 API/UI 미배선 |
| Model tier | ✅ | 세션별 `auto/flash/pro` DB 영속 + UI 복원 |
| Provider abstraction | ⚠️ | factory 경계는 있으나 current provider는 DeepSeek only |
| Vision | ✅ | 이미지가 있는 turn에서 Developer vision model route; 별도 Vision Agent는 없음 |
| Acceptance Gates | ✅ | 구현 전 gate 등록, process-owned pass/fail/evidence |
| Gate Recovery | ✅ | code change + gate 0일 때 Flash/3-step/`update_gates` 전용 1회 |
| Gate coverage completion | ✅ | gate 0 code change는 `completed` 불가 |
| Generic verification | ✅ | pytest/build + passed/failed/unavailable |
| Runtime smoke | ✅ | FORGE self-repo Playwright load/selector/uncaught check |
| Integration verification | ✅ | gate 작업 최종 상태에서 generic rerun + failed gate 확인 |
| Structured final report | ✅ | process-owned CompletionSummary, deterministic formatter, history persistence |
| Auto commit | ✅ | Agent가 write/edit로 바꾼 path만 pathspec commit |
| Auto push policy | ✅ | `completed`만 push; `completed_unverified`는 push 금지 |
| Cancellation | ✅ | run cancel + 실행 중 tool/subprocess cancellation 경로 |
| Cost budget | ✅ | run USD 누적 cap; 0 = unlimited |
| Context pruning | ✅ | command-aware compression + recoverable tool store |
| Large-file reading | ✅ | 400줄 초과 symbol map + `find_symbol`/range read |
| Compaction | ✅ | ~75% compact, ~95% block, summary/covered PostgreSQL 영속 |
| New session same workspace | ✅ | task-boundary context reset |
| Project Memory | ✅ | `{fact,source,evidence}` candidate + deterministic memory_guard + provenance |
| Memory source precedence | ✅ | current source/config > ROOM_MEMORY |
| Skills | ✅ | Curated / Learned / Project 3-tier, selective injection |
| Refinement | ✅ | repeated failure candidate → approve/ignore/rollback; skill file apply 가능 |
| Durable history | ✅ | step-level PostgreSQL history + JSONL events |
| Auto Resume | ✅ | restart interrupted run을 history 기반 headless resume + crash-loop guard |
| Independent worker/queue | ❌ | Python worker/process 자체 durable queue는 아직 없음 |
| Scheduled Jobs | ✅ | one-shot/daily/interval, timezone, DB next_run_at, atomic claim, retry |
| Deferred/Condition Jobs | ❌ | deterministic watcher/condition state 미구현 |
| Web Push | 🟡 | push device/notification 기반 존재, scheduler/condition과 완전한 제품 흐름은 추가 검증 필요 |
| MCP stdio | ✅ | execute/status/result/cancel high-level tools |
| Remote MCP transport | ❌ | HTTP/remote MCP auth/resources 미구현 |
| Mac Terminal | ✅ | host PTY + WebSocket + xterm |
| Mac Screen | ✅ | screenshot/JPEG polling, 모바일 landscape/coordinate 보정 |
| Mac mouse/keyboard | ✅ | pointer/keyboard → `/api/mac/input`, move ~25Hz throttle |
| Camera | 🟡 | imagesnap polling PoC |
| WebRTC screen/camera | ❌ | proposal only |
| Browser check | ✅ | local-origin Playwright read-only tool |
| General web search/fetch | ❌ | proposal only |
| R0 Benchmark | ✅ | 25 deterministic fixture tasks + checker self-test |
| RSI R1 | ✅ | candidate worktree/self-mod/benchmark/no-op reject/report/human promotion |
| Automatic main promotion | ❌ | 의도적으로 사람 승인 유지 |
| Tool Script/RPC | ❌ | proposal/evaluation 대상 |
| Generic ExecutionBackend | ❌ | Local/Docker/SSH 공통 abstraction 미구현 |
| Parallel fresh workers | ❌ | scheduling primitive 수준 외 실제 worker orchestration 미구현 |
| App token auth | ✅ opt-in | `FORGE_AUTH_TOKEN` 설정 시 `/api/*`(health 제외), WS, `/uploads/*` 보호 |

## Quality snapshot

Project Memory hardening commit 기준 backend suite는 **116 passed**가 보고됐다. 이 숫자는 기능 KPI가 아니라 regression safety signal이며, 이후 code 변경 시 다시 갱신해야 한다.

## 가장 중요한 미구현

- DeepSeek-only provider 경계 일반화
- independent durable worker/queue/process isolation
- Deferred/Condition Jobs
- gate semantic coverage의 장기 실사용 평가
- bounded fresh workers/parallelism(benchmark 근거가 생길 때만)
