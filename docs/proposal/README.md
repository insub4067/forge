# FORGE Proposal Index / Adoption Status

> 이 디렉터리는 설계 제안과 조사 기록이다. 현재 구현 상태의 authoritative 문서는 [`../status/work-status.md`](../status/work-status.md), [`../core/architecture.md`](../core/architecture.md), [`../core/agent-loop.md`](../core/agent-loop.md)다.

Proposal 본문은 작성 당시의 설계 의도를 보존한다. 완료된 항목을 과거 문서에서 삭제하지 않고 이 인덱스에서 반영 상태만 관리한다.

## DeepSeek Harness

[`deepseek-harness-adoption.md`](deepseek-harness-adoption.md)

- ✅ Tool-result pruning
- ✅ Context compaction
- ✅ Model surface / stored history 분리
- ✅ Provider retry/recovery
- ✅ read-only parallel tools
- ✅ JSONL event logging
- ⬜ authoritative event replay / true resume
- ⬜ Tool Script/RPC

## Claude Code Clean-room

[`claude-code-cleanroom-adoption.md`](claude-code-cleanroom-adoption.md)

- ✅ Task lifecycle
- ✅ Reviewer/Debugger correction loop
- ✅ Permission/approval boundary
- ✅ Runtime steering / live status
- ⬜ Coordinator / isolated workers
- ⬜ durable background worker

## Hermes Agent

[`hermes-agent-adoption.md`](hermes-agent-adoption.md)

- ✅ Self-Improving Skills 1차
- ✅ Selective Skill Retrieval
- ✅ Prompt-cache-first stable prefix
- ✅ Session search / metrics
- ⬜ Tool Script/RPC
- ⬜ Scheduled/Condition Jobs
- ⬜ ExecutionBackend / isolated subagents

## Product / Capability Proposals

- [`tauri-desktop-host.md`](tauri-desktop-host.md) — Desktop Host / sidecar
- [`web-search-tools.md`](web-search-tools.md) — bounded web_search / web_fetch
- [`vision-agent.md`](vision-agent.md) — Vision routing 및 고도화 기록

## 판단 원칙

FORGE는 기능 개수보다 **cost per successfully completed task**를 최상위 기준으로 둔다. Proposal은 benchmark와 실제 병목이 확인될 때 구현 우선순위를 얻는다.
