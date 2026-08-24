# FORGE Proposal Index

> Proposal 본문은 **당시 설계/실험 기록**으로 보존한다. 현재 구현 여부는 이 index가 authority이며, 실제 코드가 최종 authority다.

상태 의미: `implemented` / `partial` / `proposal` / `deferred` / `superseded` / `rejected-experiment`.

| Proposal | 현재 상태 | 2026-08-24 source 기준 메모 |
|---|---|---|
| `browser-computer-use.md` | partial | local-only `browser_check`/self runtime smoke 구현. full browser/computer-use는 미구현. PWA 사람용 Mac input은 별도 기능으로 구현됨. |
| `claude-code-cleanroom-adoption.md` | superseded/absorbed | task/permission/verification 아이디어 일부 흡수. 문서의 고정 Planner/Coder/Reviewer/Debugger 구조는 현재와 다름. |
| `deepseek-harness-adoption.md` | absorbed | compaction, tool pruning, durable events, cancellation/recovery 등 다수 흡수. 당시 role pipeline은 현재와 다름. |
| `durable-worker-resume.md` | partial | history-based Auto Resume + crash-loop guard 구현. independent durable worker/queue/checkpoint continuation은 미구현. |
| `forge-mcp-agent-runtime.md` | partial | stdio `execute/status/result/cancel` 4 tools 구현. remote MCP/resources는 미구현. |
| `forge-runtime-hardening-roadmap.md` | mostly absorbed | verification/approval/context/RSI hardening 다수 완료. provider/workers 일부 남음. |
| `gate-coverage-enforcement.md` | implemented | G0 telemetry + gate 0 completion policy + 1회 recovery. 이후 Developer가 구현 전 gate를 정상 생성하도록 prompt 강화. |
| `global-workspace-skills.md` | implemented/diverged | 실제는 Curated/Learned/Project 3-tier + selective retrieval. proposal의 2-tier 가정은 과거. |
| `hermes-agent-adoption.md` | partial | Skills/context/scheduler/narrow core 아이디어 일부 반영. Tool Script, generic ExecutionBackend, subagents는 미구현. |
| `home-camera-monitor.md` | PoC only | `imagesnap` polling Camera PoC. WebRTC/registry/RTSP/condition detection은 미구현. |
| `live-screen-preview.md` | implemented/diverged | 현재 screenshot JPEG polling + 사람용 mouse/keyboard input. proposal의 WebRTC view-only 구조는 구현되지 않음. |
| `low-cost-model-routing.md` | rejected-experiment / future | current main은 DeepSeek only. Ox 제거, Ling/OpenRouter 실험도 repeated tool-call 문제로 revert. CPS 평가 틀만 유효. |
| `onprem-inference-optimization.md` | deferred | OpenAI-compatible internal provider/vLLM/SGLang/speculative serving은 현재 미구현. 실제 사내 inference 요구/hardware가 생기면 재검토. |
| `prime-agent-adoption.md` | partial | refinement candidate/apply/rollback, budget guard 등 일부 구현. Tool RPC/bounded workers는 미구현. |
| `recursive-self-improvement.md` | partial/advanced | R0 25 tasks + R1 candidate worktree/self-mod/no-op reject/promotion report 구현. 자동 main promotion은 의도적으로 없음. |
| `remote-terminal.md` | implemented/diverged | 현재 host PTY + WebSocket/xterm. proposal의 Docker-only/durable reconnect session 모델과 다름. |
| `scheduled-condition-jobs.md` | partial | one-shot/daily/interval, timezone, next_run_at, atomic claim/retry 구현. Deferred/Condition watcher는 미구현. |
| `task-boundary-project-memory.md` | implemented/hardened | completed evidence에서 Project Memory 추출 + provenance/memory_guard 구현. 자유 LLM memory 방식은 오염 사례 후 폐기. |
| `tauri-desktop-host.md` | proposal | Tauri host 미구현. PWA/FastAPI 구조 유지. |
| `token-cost-reduction.md` | living analysis | 과거 planner 비용 실측은 역사 데이터. 현재 adaptive Planner, compaction persistence 등으로 runtime 가정이 달라짐. |
| `vision-agent.md` | superseded/absorbed | vision은 별도 Agent/table이 아니라 이미지 turn의 Developer model route로 통합. |
| `web-search-tools.md` | proposal | general web_search/web_fetch 미구현. `browser_check`는 local-origin 전용이라 대체 기능이 아님. |

## 읽는 법

- 구현을 확인하려면 `../status/work-status.md`, `../core/*`, 실제 source를 본다.
- proposal의 가격/모델/구조는 작성 시점 snapshot으로만 해석한다.
- 과거 실험이 revert된 경우 proposal을 지우지 않고 `rejected-experiment`로 남긴다.
- 새로운 proposal을 추가할 때 이 index의 현재 상태도 함께 관리한다.
