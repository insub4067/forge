# FORGE

**English** | [한국어](README.ko.md)

A self-hosted **agentic coding runtime** that executes, verifies, repairs, and resumes software work on a Mac while remaining controllable from a mobile PWA.

## Core Thesis

FORGE is **not** primarily about running LLMs cheaply.

> **The key is to make inexpensive models reliable through a strong harness and deterministic quality-control process.**

Quality is not delegated to the model's confidence. The process verifies real artifacts with tests/builds, repairs failures, and escalates to a stronger model only when needed.

```text
Inexpensive model
  ↓
bounded execution loop
  ↓
real code/tool actions
  ↓
deterministic test/build verification
  ├─ PASS → completed / commit
  └─ FAIL → diagnose / repair / verify again
                         ↓ only when stuck: stronger model
```

Optimization order is therefore: **success/quality first → verified completion → cost per successful task → elapsed time → human intervention**. Saving tokens while reducing success rate is not an improvement.

## Current Runtime

```text
User Goal
  ↓
Triage
  ├─ CHAT → Chat (Flash)
  └─ AGENT → Developer (Flash + thinking)
               ↻ Plan → Execute → Self-verify/Repair
               ↓ Pro escalation when needed
               ↓
          Strict Verification Gate
          real test/build execution
               ├─ PASS → completed → auto commit/push allowed
               └─ FAIL → bounded repair → verification_failed
```

The default pipeline does not use separate Planner/Reviewer/Debugger agents. One Developer owns the working context end-to-end, while the final quality authority is the process-level verification gate—not the model saying "done".

## Current Implementation

- DeepSeek V4 provider (Flash/Pro/Vision routing), streaming, tool calling and thinking
- Flash-first with bounded Pro escalation
- all-in-one Developer loop
- **Strict Verification Gate** running real build/pytest checks
- bounded repair after verification failure
- auto commit/push only on verified completion paths
- step-level history persistence
- **Durable Auto Resume** for unfinished runs after server restart, with crash-loop guard
- PostgreSQL persistence / JSONL event log / metrics
- context pruning / compaction / cache telemetry
- Curated / Learned / Project three-tier Skills
- deterministic R0 benchmark harness with 21 tasks
- bounded RSI promotion gate: success rate → cost per success → elapsed
- Docker Sandbox by default + opt-in Host mode
- application-level HTTP/WebSocket auth via `FORGE_AUTH_TOKEN`
- mobile PWA organized around Sessions / Automation / Mac
- Git / Files / Skills / Metrics / Kanban / Vision
- Mac host PTY Terminal / screen view / camera PoC
- scheduled-job foundations

## Major Remaining Work

- harden approval/capability boundaries during Durable Resume
- distinguish verification `PASSED / FAILED / UNAVAILABLE`
- expand benchmark coverage and compare against external harnesses
- complete bounded RSI R1: candidate worktree → benchmark → human promotion
- finish restart/idempotency/timezone semantics for Scheduled / Deferred / Condition Jobs
- Tool Script/RPC Mode
- ExecutionBackend cleanup (Local/Docker/SSH)

## Security

FORGE can modify files, execute shell commands, change Git repositories, expose a host PTY terminal, and access screen/camera capabilities. Do not expose it directly to the public Internet.

A Cloudflare Tunnel alone is not authorization. Use Cloudflare Zero Trust / Access, Tailscale, a VPN, or equivalent network controls, while keeping application-level `FORGE_AUTH_TOKEN` protection enabled independently.

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

Use [`docs/README.md`](docs/README.md) as the authoritative documentation index. Prefer current code plus `docs/core` and `docs/status` over Proposal/Archive documents.

## License

MIT
