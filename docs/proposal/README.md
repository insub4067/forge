# FORGE Proposal Index / Adoption Status

> Proposal은 설계 의도를 보존한다. 현재 구현 판단은 [`../status/work-status.md`](../status/work-status.md), [`../core/architecture.md`](../core/architecture.md), [`../core/agent-loop.md`](../core/agent-loop.md)을 우선한다.

## Harness Adoption

### DeepSeek Harness

[`deepseek-harness-adoption.md`](deepseek-harness-adoption.md)

- ✅ Tool-result pruning / Context compaction
- ✅ Provider retry/recovery / reasoning 400 session optimization
- ✅ read-only parallel tools / JSONL event logging
- ⬜ authoritative event replay / true resume
- ⬜ Tool Script/RPC

### Claude Code Clean-room

[`claude-code-cleanroom-adoption.md`](claude-code-cleanroom-adoption.md)

- ✅ Task lifecycle / Reviewer-Debugger loop
- ✅ Permission boundary / runtime steering
- ⬜ Coordinator / isolated workers
- ⬜ durable background worker

### Hermes Agent

[`hermes-agent-adoption.md`](hermes-agent-adoption.md)

- ✅ Self-Improving Skills / selective retrieval / stable prefix
- ✅ Session search / metrics
- ⬜ Tool Script/RPC
- 🟡 Scheduled/Condition Jobs
- ⬜ ExecutionBackend / isolated subagents

## Product / Capability

- [`global-workspace-skills.md`](global-workspace-skills.md) — Global+Workspace 2-tier skill: **G0/G1 구현됨**(병합·override·경계·save_skill scope·UI 배지, `~/.forge/skills` 인덱스 README). G3 telemetry·G4 promotion 미구현
- [`forge-mcp-agent-runtime.md`](forge-mcp-agent-runtime.md) — FORGE를 MCP 호출 가능한 autonomous execution runtime으로(forge_execute/status/result/cancel). **설계 proposal**. 선결: 보안경계·Runtime Boundary·[[durable-worker-resume]]. 미구현
- [`durable-worker-resume.md`](durable-worker-resume.md) — Durable Worker/Resume: **설계 proposal**(role 경계 체크포인트→opt-in 재개→worker 분리). 외부 감사가 지적한 최대 reliability gap. 미구현
- [`recursive-self-improvement.md`](recursive-self-improvement.md) — bounded RSI: **설계 proposal**(telemetry→worktree→고정benchmark→사전식 게이트→사람 승인). 미구현. 선결은 R0 결정적 benchmark 하네스
- [`tauri-desktop-host.md`](tauri-desktop-host.md) — Desktop Host / sidecar: proposal
- [`web-search-tools.md`](web-search-tools.md) — bounded web search/fetch: proposal (보류 권장 — 실측 병목 근거 없음, planner 63% 등이 우선)
- [`vision-agent.md`](vision-agent.md) — Vision: 일부 구현
- [`scheduled-condition-jobs.md`](scheduled-condition-jobs.md) — 예약/조건 실행: **기반 구현 진행 중**
- [`remote-terminal.md`](remote-terminal.md) — **v1 구현됨. 단, proposal의 Docker-only가 아니라 현재는 Mac host PTY**
- [`live-screen-preview.md`](live-screen-preview.md) — **view-only 화면 보기 1차 구현됨**; WebRTC 고도화는 미구현
- [`home-camera-monitor.md`](home-camera-monitor.md) — **Mac camera JPEG polling PoC 구현됨**; WebRTC/Condition 연동은 미구현

## 구현과 Proposal이 다른 부분

Proposal은 미래 설계이므로 실제 코드와 다를 수 있다.

- Terminal: 설계는 Docker sandbox 우선이었으나 실제 v1은 개인 Mac host PTY + WebSocket + xterm.js로 구현됐다.
- Camera: 설계는 WebRTC 중심이었으나 실제 PoC는 `imagesnap` JPEG polling이다.
- Screen: view-only 기능은 구현됐지만 WebRTC 기반 저지연 streaming은 아직 아니다.

이 차이는 proposal 본문을 과거 사실처럼 덮어쓰지 않고 이 index와 status 문서에서 명시한다.

## 판단 원칙

FORGE는 기능 개수보다 **cost per successfully completed task**를 최상위 기준으로 둔다. 원격 host capability는 성능보다 보안 경계를 먼저 검증하고, RSI는 candidate → benchmark → promotion/rollback이 닫히기 전까지 bounded/human-triggered self-improvement로 취급한다.
