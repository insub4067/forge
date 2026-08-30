# FORGE Documentation

> 문서 감사 기준: 2026-08-24 `main` source. **판단 순서: 현재 코드 → Current State 문서 → Operations/Planning → Proposal → 날짜형 Decision/Handoff → Archive.**

## Project Thesis

FORGE는 특정 모델의 wrapper가 아니라 **검증 가능한 autonomous coding runtime**이다. 저렴한 모델을 쓰는 것 자체가 목표가 아니며, process-owned verification을 유지한 상태에서 성공 작업당 비용과 인간 개입을 줄인다.

## Current State — authoritative

1. [`status/work-status.md`](status/work-status.md) — 지금 구현된 것, 알려진 위험, 다음 우선순위
2. [`core/architecture.md`](core/architecture.md) — 실제 컴포넌트/경계
3. [`core/agent-loop.md`](core/agent-loop.md) — routing → execution → verification → completion
4. [`core/spec.md`](core/spec.md) — 현재 제품 요구사항/불변식
5. [`status/features.md`](status/features.md) — 구현 matrix
6. [`core/db-schema.md`](core/db-schema.md) — persistence schema
7. [`core/skills.md`](core/skills.md) — Curated/Learned/Project Skills
8. [`core/trust-boundary.md`](core/trust-boundary.md) — 신뢰 경계: 무엇을 신뢰하지 않는가, 실행·쓰기 경계는 어디서 강제되는가

Current State 문서가 코드와 다르면 **코드가 authority**이며 문서를 즉시 고친다.

## Runtime Prompts

`docs/agents/*.md`는 일반 문서가 아니라 Runtime에 실제 주입되는 role prompt다.

- `chat.md` — 읽기 전용 대화
- `developer.md` — 유일한 mutation executor, gate 등록/execute/repair
- `planner.md` — complex 작업의 fresh read-only 계획
- `reviewer.md` — complex 작업의 fresh independent review
- `gate_recovery.md` — gate 누락 시 1회 안전망
- `orchestrator.md` — 실행 정책 설명

프롬프트 변경은 `_load_role()`이 매 호출 파일을 읽으므로 backend 재시작 없이 다음 role call부터 반영된다. Python runtime 코드를 바꾸면 재시작이 필요하다.

## Operations

- [`operations/benchmark.md`](operations/benchmark.md) — 25-task deterministic R0 + RSI 평가
- [`operations/mcp-server.md`](operations/mcp-server.md) / [`operations/mcp-connect-guide.md`](operations/mcp-connect-guide.md) — stdio MCP 운영
- [`operations/troubleshooting.md`](operations/troubleshooting.md) — 현재 장애/검증 절차

## Planning

- [`planning/roadmap-priority.md`](planning/roadmap-priority.md) — 현재 우선순위
- [`planning/improvement-plan.md`](planning/improvement-plan.md) — 단기 실행 계획

## Proposals

`proposal/`은 **설계/실험의 역사 기록**이다. 구현 후에도 당시 가정과 대안을 보존하기 위해 본문을 현재형으로 억지 수정하지 않는다. 각 proposal의 현재 반영 상태는 [`proposal/README.md`](proposal/README.md)에서 관리한다.

따라서 proposal에 “미구현”, “view-only”, “Planner 없음” 같은 과거 문장이 있어도 현재 기능을 판단할 때 직접 인용하지 않는다.

## Decision / Handoff / Archive

- `status/agent-mode-decision-*`, `architecture-decision-*`, `handoff-*`는 해당 날짜의 판단/인수인계 스냅샷이다.
- `archive/`는 더 오래된 제품 스펙 기록이다.
- 이 문서들은 역사 보존용이며 최신 상태 판단에 쓰지 않는다.

## Freshness Policy

문서 변경 시 다음을 지킨다.

1. source와 test/commit evidence를 먼저 확인한다.
2. Current State 문서는 현재형으로 정확하게 유지한다.
3. Proposal/Decision/Handoff는 원문을 보존하고 index에서 `implemented / partial / deferred / superseded / rejected` 상태를 갱신한다.
4. “계획”을 “구현됨”처럼 쓰지 않는다.
5. 테스트 개수·provider·모델·가격처럼 빠르게 변하는 수치는 근거 commit/source가 있을 때만 쓴다.
