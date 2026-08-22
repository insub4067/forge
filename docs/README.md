# FORGE Documentation Index

> 문서 동기화 기준: 2026-08-22 `main`

## Authoritative Current-State Docs

현재 구현 상태를 판단할 때 아래 순서로 본다.

1. [`work_status.md`](work_status.md) — 완료/미완료/다음 작업
2. [`architecture.md`](architecture.md) — 실제 런타임 구조
3. [`agent-loop.md`](agent-loop.md) — Agent 실행/복구/context/model policy
4. [`feat.md`](feat.md) — 기능별 구현 상태
5. [`db-schema.md`](db-schema.md) — persistence/telemetry
6. [`spec.md`](spec.md) — 현재 제품 범위/요구사항
7. [`../README.md`](../README.md) — 프로젝트 개요

## Operations / Measurement

- [`benchmark.md`](benchmark.md) — cost per successfully completed task benchmark
- [`troubleshooting.md`](troubleshooting.md) — 실제 운영 장애와 해결 기록

## Product Specification

- [`AGENTIC_CODING_AI_SPEC.md`](AGENTIC_CODING_AI_SPEC.md) — 제품 비전/UX/Agent 방향

## Runtime Prompt Files

`agents/*.md`는 단순 문서가 아니라 `AgentRuntime`이 실제 system prompt에 로드하는 역할 정책이다.

- `agents/planner.md`
- `agents/coder.md`
- `agents/reviewer.md`
- `agents/debugger.md`
- `agents/chat.md`
- `agents/orchestrator.md`

따라서 문서 정리만을 목적으로 이 파일을 수정하면 Runtime behavior가 바뀐다. 역할 정책 변경이 필요할 때만 코드 변경과 동일한 수준으로 검토한다.

## Proposal / Historical Design Records

[`proposal/`](proposal/)은 DeepSeek Harness, Claude Code 공개 분석, Hermes Agent 등의 설계에서 FORGE에 적용할 아이디어를 정리한 제안 기록이다.

현재 반영 여부는 [`proposal/README.md`](proposal/README.md)를 기준으로 확인한다. 개별 proposal 본문은 작성 시점의 설계 의도를 보존하기 위해 과거 제안을 임의로 삭제하거나 현재 구현 문서처럼 재작성하지 않는다.

## Current Architectural Truths

- Planner는 Pro 기본이 아니라 **Flash 기본 / COMPLEX만 Pro**다.
- Context pressure는 누적 비용 token이 아니라 provider 실측 `prompt_tokens` 기준이다.
- 75% compaction, 95% hard block 정책을 사용한다.
- PostgreSQL은 실제 session/history/task/telemetry 저장에 사용 중이다.
- Redis는 현재 durable worker/event replay의 authoritative 경로가 아니다.
- JSONL durable event/action log는 구현되어 있다.
- 서버 재시작 시 interrupted run을 감지/정리하지만 실행 stack resume은 아직 아니다.
- 기본 bash 실행은 Docker Sandbox이며 `SANDBOX_MODE=host`는 명시적 옵트인이다.
- PWA는 SSE + `/status` polling으로 실행 상태를 복구한다.
- 핵심 최적화 지표는 **cost per successfully completed task**다.
