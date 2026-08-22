# FORGE

**English** | [한국어](README.ko.md)

A self-hosted **agentic coding runtime** that turns natural-language goals into an iterative plan → execute → review → fix → re-review workflow. FORGE is designed to run for long periods on a Mac while remaining controllable from a mobile PWA.

FORGE optimizes for **completing the same task with equal or better success rates using fewer tokens, API calls, time, and cost**. The primary metric is not `tokens/task`, but **cost per successfully completed task**.

```text
User Goal
  ↓
Triage (Flash)
  ↓
Planner (Flash by default / Pro only for COMPLEX tasks)
  ↓
Coder (Flash)
  ↓
Reviewer (Flash)
  ↓
Debugger (Flash → Pro only for the final recovery attempt)
  ↓
Re-review / Done
```

## ⚠️ Security Warning

FORGE is not a normal chat application. It is a coding agent that can read and modify files inside configured workspaces, execute shell commands, and change Git repositories.

**Do not expose a FORGE instance directly to the public Internet.** Unauthorized access could potentially allow someone to:

- read or modify files inside accessible workspaces
- execute shell commands
- modify Git repositories
- consume configured LLM API quota or credentials indirectly
- gain broader access to the host when host execution mode is enabled

FORGE's application-level authentication should **not** be treated as a replacement for a proper network access-control layer. For remote access, place FORGE behind a trusted boundary such as **Cloudflare Zero Trust / Access, Tailscale, a VPN, or another authenticated private network**.

The development deployment used by this project is protected by **explicit Cloudflare Zero Trust Access policies**. A Cloudflare Tunnel by itself does not provide user authorization; if you attach FORGE to a public hostname through a tunnel, configure Cloudflare Access policies separately.

Keep the default Docker sandbox enabled whenever possible. `SANDBOX_MODE=host` should only be used in a trusted personal environment when you understand the implications. **Never expose host execution mode to an untrusted network.**

## Current Status

- Phase 1 — Agent Core: complete
- Phase 2 — Code Modification: complete
- Phase 3 — Remote Operation: in progress

Implemented highlights:

- DeepSeek V4 streaming / tool calling / thinking
- Flash-first, Pro-on-demand model routing
- Reviewer ↔ Debugger state-based self-correction loop
- read/write/edit/bash/grep/list tools with approval gates
- Docker Sandbox by default + opt-in `SANDBOX_MODE=host`
- Git checkpoints and unified diffs
- Tool-result pruning + 75% context compaction + 95% hard block
- DeepSeek cache hit/miss telemetry + stable prefix hash
- Selective Skill retrieval + `save_skill` Self-Improving Skills
- Parallel prefetch for read-only tools
- Recovery for 429/5xx/timeouts and `reasoning_content` errors
- PostgreSQL persistence for sessions, messages, tasks, checkpoints, and agent runs
- Agent-run telemetry for success rate, cost, cache efficiency, and Pro escalation
- Concurrent-run guard per session and runtime message injection
- Interrupted-run detection after server restart (true execution resume is not implemented yet)
- JSONL durable action/event log
- `/sessions/{id}/status` for running role, activity, approval/question waits, and idle state
- 600-second approval/question timeout and cancellation cleanup
- Required workspace selection and workspace-bound file APIs
- Mobile PWA for sessions, Kanban, Git, files, Skills, metrics, approvals, questions, and live activity
- Multi-image attachments with Vision analysis and swipeable fullscreen gallery
- Model-surface image stripping for non-vision roles while preserving original history
- Dedicated run-history and error-log detail views
- `/status` recovery and polling when SSE disconnects before `done`
- Collapsible Skills UI

## Execution Modes

The default execution mode is the isolated Docker sandbox. Host execution is available only as an explicit opt-in:

```bash
SANDBOX_MODE=host
```

Host mode gives the agent broader access to local tools and makes self-verification easier, but provides substantially less isolation. Use it only in a trusted personal environment.

## Remote Runtime

An agent run can continue on the server after the browser SSE connection is lost. The PWA polls `/status` to recover the current role and activity. If the server process itself restarts, FORGE reconciles stale `sessions.running` state and records the interruption in history.

**True durable resume from the exact execution step after a process restart is not implemented yet.** A separated durable worker and replayable authoritative event stream remain major roadmap items.

## Efficiency Strategy

1. Flash-first / Pro-on-demand routing
2. Stable prompt prefixes and cache-hit tracking
3. Inject only relevant Skills
4. Model-free pruning of oversized tool results
5. Parallel execution for safe read-only tools
6. Non-destructive context compaction at 75% pressure
7. Retry, Debugger, and Pro escalation only after failure
8. Measure every optimization against `cost per successfully completed task`

## Getting Started

### Requirements

- Docker + Docker Compose
- Python 3.12+
- Node.js 18+
- A supported DeepSeek API configuration

### Backend and infrastructure

```bash
docker compose up -d
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790
```

### Frontend

```bash
cd frontend
npm install
npm run build
```

## Documentation

Start with the [`docs/README.md`](docs/README.md) documentation index.

- [`docs/core/`](docs/core/) — architecture, runtime flow, schema, requirements
- [`docs/status/`](docs/status/) — implementation and feature status
- [`docs/operations/`](docs/operations/) — benchmark and troubleshooting
- [`docs/planning/`](docs/planning/) — roadmap and improvement plan
- [`docs/proposal/`](docs/proposal/) — design proposals and adoption research
- [`docs/archive/`](docs/archive/) — historical, non-authoritative documents

`docs/agents/` contains **live runtime prompt files**, not ordinary documentation.

## Next Major Work

- True durable worker resume and event replay
- Tool Script/RPC Mode
- Scheduled / Condition Jobs + Web Push
- ExecutionBackend abstraction (Local → SSH → Docker)
- Isolated subagents after the runtime foundation is stable

## License

MIT
