# FORGE Documentation

> 현재 구현 판단은 **코드 → Current State 문서 → Proposal → Archive** 순으로 한다.

## Project Thesis

FORGE의 핵심은 단순한 저비용 실행이 아니다.

> **저렴한 모델도 강한 Harness의 실행·검증·수리·복구 프로세스 안에서 사용해 결과 품질을 보장한다.**

비용 최적화는 success/verification guardrail을 통과한 뒤에만 평가한다.

## Current State

1. `status/work-status.md` — 현재 완료/미완료/다음 작업
2. `core/architecture.md` — 실제 시스템 구조
3. `core/agent-loop.md` — 실행/검증/복구/model policy
4. `status/features.md` — 기능 matrix
5. `core/skills.md` — 3-tier Skills
6. `core/db-schema.md` — persistence/telemetry
7. `core/spec.md` — 제품 요구사항

## Operations & Evaluation

- `operations/benchmark.md` — 품질 우선 deterministic benchmark
- `operations/troubleshooting.md` — 운영 장애/해결 기록
- `operations/mcp-server.md`, `mcp-connect-guide.md` — MCP 운영 문서

## Planning

- `planning/roadmap-priority.md` — 현재 전략 우선순위
- `planning/improvement-plan.md` — 단기 개선 계획

## Runtime Prompts

`agents/`는 실제 Runtime behavior에 영향을 주는 prompt 파일이다.

현재 파일:

- `agents/chat.md`
- `agents/developer.md`
- `agents/orchestrator.md`
- `agents/planner.md`
- `agents/reviewer.md`

일부 파일은 역사/외부 경로용일 수 있으므로 "파일이 존재한다"와 "현재 기본 Agent pipeline에서 호출된다"를 구분한다. 현재 기본 파이프라인의 authority는 `core/agent-loop.md`와 실제 Runtime 코드다.

## Proposals

`proposal/`은 설계/조사 기록이다. 이미 구현된 proposal도 원문을 역사 기록으로 보존할 수 있다. 현재 반영 여부는 `proposal/README.md`에서 확인한다.

## Status / Decision Records

`status/`의 날짜가 붙은 decision/handoff 문서는 당시 판단 기록이다. 최신 `work-status.md`와 충돌하면 최신 코드와 work-status를 우선한다.

## Archive

`archive/`는 현재 구현 판단에 사용하지 않는다.

## Directory Policy

```text
docs/
├─ README.md
├─ core/
├─ status/
├─ operations/
├─ planning/
├─ agents/
├─ proposal/
└─ archive/
```

문서가 코드와 달라지면 코드에 맞춰 Current State 문서를 즉시 수정한다. Proposal/Decision 기록은 역사성을 보존하되 인덱스에서 현재 상태를 명시한다.
