# FORGE

**English** | [한국어](README.ko.md)

A self-hosted **agentic coding runtime** that modifies real code, verifies user requirements and test/build outcomes at the process level, repairs bounded failures, survives long-running work on a Mac, and stays controllable from a mobile PWA.

## North Star

FORGE is not about using the cheapest model.

> **Use an appropriate model inside a strong execution, verification, repair, and recovery harness so the user can keep delegating real development work with confidence.**

Optimization order: `verified correctness → verified completion → user trust/autonomy → cost_per_verified_task → elapsed → human intervention`. A model saying “done” is never the completion authority.

## Current Flow

```text
Room mode
├─ chat → read-only Chat
├─ work → coding path directly
└─ auto → Triage selects chat/work

Coding path
├─ simple  → Developer
└─ complex → Planner → Developer → fresh Reviewer
                          └ FAIL → one Developer repair

Developer
→ register Acceptance Gates before implementation
→ Execute
→ Generic Verification (test/build/runtime smoke)
→ Acceptance Gate Verification
→ Integration Verification
→ process-owned CompletionSummary
```

Complexity is selected automatically today. `multi/single` override rules exist internally but are not wired to user-facing API/UI controls.

## Reliability Contract

- A code-changing run with zero acceptance gates cannot become `completed`.
- If Developer misses gates, a Flash-only `gate_recovery` turn gets one attempt, at most 3 steps, with only `update_gates` available.
- If gates are still absent, the run ends as `completed_unverified`.
- Generic verification distinguishes `passed / failed / unavailable`.
- Acceptance evidence records the actual command, exit code and output; gate commands run through `DockerSandbox.run_verify()` rather than a privileged host-shell bypass.
- Only `completed` may auto-push. `completed_unverified` may commit locally but does not push; `verification_failed` does neither.
- Final reports are deterministically built from process-owned gate/test/integration/commit/push facts and persisted in history.

## Models and Context

- The current provider implementation is **DeepSeek only**. The OpenRouter/Ling experiment was removed from `main`.
- Developer is Flash-first with bounded Pro escalation; per-session `auto / flash / pro` policy is persisted and restored.
- Planner and Reviewer use short, fresh Flash contexts.
- Large files use symbol maps and `find_symbol`; long tool results are pruned with recoverable `read_tool_result` storage.
- Compaction starts around 75% and hard-blocks around 95%; the compacted summary is persisted in PostgreSQL across runs.
- Project memory is evidence-bound and provenance-validated. Current source/config always outranks remembered facts.

## Implemented Today

- FastAPI + Vue 3/Vite PWA + PostgreSQL
- DeepSeek streaming, tool calling, thinking and vision routing
- adaptive Planner → Developer → Reviewer plus single-Developer path
- Acceptance Gate Ledger, Gate Recovery, deterministic CompletionSummary
- Generic/Acceptance/Integration verification and Playwright self-runtime smoke
- bounded repair, Pro escalation, repeated-tool guard and cancellable subprocesses
- Durable Auto Resume with crash-loop guard and persisted auto-approve/model-tier policy
- per-run USD budget guardrail
- Curated / Learned / Project Skills plus refinement approval/rollback
- evidence-bound Project Memory validation
- deterministic R0 benchmark with **25 tasks**
- bounded RSI R1 candidate worktree → benchmark → no-op reject → human promotion
- Scheduled Jobs: one-shot/daily/interval, timezone, durable `next_run_at`, atomic claim, retry
- MCP stdio: `forge_execute`, `forge_status`, `forge_result`, `forge_cancel`
- mobile sessions/automation/Kanban/files/Git/Skills/Metrics/approval/steering
- Mac host PTY terminal over WebSocket, screen polling, pointer/keyboard remote input, camera PoC
- `FORGE_AUTH_TOKEN` protection for `/api/*` and `/uploads/*` when enabled

The latest memory-hardening source commit reported **116 backend tests passing**.

## Next Priorities

1. Dogfood gate semantic quality, false negatives, and intervention rate.
2. Generalize the DeepSeek-only provider boundary with an OpenAI-compatible adapter while protecting verified success rate.
3. Finish Deferred/Condition scheduling semantics and strengthen durable worker/process isolation.
4. Add fresh-context workers/parallelism only when benchmarked independence and verified throughput justify the extra complexity.
5. Treat Tool Script/RPC and broader ExecutionBackend abstractions as evidence-driven optimizations, not mandatory architecture.

## Security

FORGE can modify files, execute shell/Git actions, expose a host PTY, and access screen/keyboard/camera capabilities. Do not expose it directly to the public Internet. A Cloudflare Tunnel alone is not authorization: use Zero Trust/VPN/Tailscale or equivalent network controls and enable `FORGE_AUTH_TOKEN` independently. Host mode and auto-approve are high-trust options.

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

[`docs/README.md`](docs/README.md) is the documentation authority map. Prefer **current source → `docs/core`/`docs/status` → operations/planning → proposal → archive/handoff**.

## License

MIT
