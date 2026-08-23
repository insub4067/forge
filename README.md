# FORGE

**English** | [한국어](README.ko.md)

A self-hosted **agentic coding runtime** that executes, reviews, and repairs work iteratively while running on a Mac and remaining controllable from a mobile PWA.

FORGE optimizes for **equal or better task success with fewer tokens, API calls, time, and cost**. The primary metric is **cost per successfully completed task**.

```text
User Goal
  ↓
Triage (Flash, lightweight router)
  ├─ CHAT → Chat
  └─ AGENT → Developer (flash + thinking medium)
               loop: Plan(3 lines) → Execute → Verify(tests/build) → done
                                          └ fail → Diagnose → Repair → Verify
               ↓ if stuck: escalate to pro + thinking high (Sr), up to 2 retries
```

Roles: Triage (cheap router) → Chat (cheapest flash) for small talk, or Developer for code. Plus Vision for images. No separate Planner/Reviewer/Debugger — each
extra agent re-reads the whole context (input tokens). One Developer owns design, implementation,
self-verification and repair end-to-end in a single context.

## ⚠️ Security Warning

FORGE can modify files, execute shell commands, change Git repositories, and now exposes Mac remote capabilities including a **host PTY terminal, screen viewing, and camera viewing**. Do not expose a FORGE instance directly to the public Internet.

A Cloudflare Tunnel alone is not authorization. Put remote deployments behind **Cloudflare Zero Trust / Access, Tailscale, a VPN, or another trusted access-control layer**. The project's development deployment uses explicit Cloudflare Zero Trust Access policies.

The Host Terminal is effectively a remote shell. Application-level WebSocket authorization and network access controls must be independently verified.

## Current Implementation

- DeepSeek V4 streaming / tool calling / thinking
- All-in-one Developer (design + implement + self-verify + repair); flash+think default, pro on failure (Jr→Sr)
- Flash-first / Pro-on-demand routing
- context pruning / 75% compaction / 95% hard block
- cache telemetry + selective Self-Improving Skills
- reasoning_content recovery and repeated-retry elimination per affected session
- read/write/edit/bash/grep/list tools with approval boundaries
- `build_frontend` host-build tool so FORGE can modify and production-build its own frontend
- Docker Sandbox by default + opt-in `SANDBOX_MODE=host`
- PostgreSQL persistence / agent telemetry / JSONL event log
- `/status` recovery after SSE loss and pending-approval restoration
- mobile PWA organized around Sessions / Automation / Mac remote operation
- Git / Files / Skills / Metrics / Kanban / Vision
- view-only Mac screen
- Mac host PTY + WebSocket + xterm.js Terminal
- Mac camera via `imagesnap` JPEG polling PoC
- scheduled-job foundations and workspace fallback

## Major Remaining Work

- Durable Worker + authoritative event replay for true restart continuation
- security review of Terminal / Screen / Camera authorization boundaries
- complete Scheduled / Deferred / Condition Jobs + Web Push
- Tool Script/RPC Mode
- ExecutionBackend abstraction
- bounded RSI pipeline: candidate → benchmark → promotion/rollback

FORGE can already modify its own repository and perform parts of its own build workflow, but it is not treated as fully recursive self-improving until evaluation and promotion are automatically closed-loop.

## Getting Started

```bash
docker compose up -d
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790
```

Frontend:

```bash
cd frontend
npm install
npm run build
```

## Documentation

Use [`docs/README.md`](docs/README.md) as the authoritative documentation index.

- `docs/core/` — current architecture and Agent loop
- `docs/status/` — actual implementation status
- `docs/operations/` — benchmarks and troubleshooting
- `docs/planning/` — roadmap
- `docs/proposal/` — proposals and adoption research
- `docs/agents/` — **live runtime prompts**

## License

MIT
