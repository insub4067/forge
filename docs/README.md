# FORGE Documentation

> 현재 구현 판단은 코드와 이 인덱스의 **Current State** 문서를 우선한다. Proposal과 Archive는 현재 구현의 authoritative source가 아니다.

## Current State

현재 상태를 확인할 때 다음 순서로 본다.

1. [`status/work-status.md`](status/work-status.md) — 완료/미완료/다음 작업
2. [`core/architecture.md`](core/architecture.md) — 실제 시스템 구조
3. [`core/agent-loop.md`](core/agent-loop.md) — Agent 실행·복구·context·model policy
4. [`status/features.md`](status/features.md) — 기능별 구현 상태
5. [`core/db-schema.md`](core/db-schema.md) — persistence / telemetry
6. [`core/spec.md`](core/spec.md) — 현재 요구사항과 제품 범위

## Planning

- [`planning/roadmap-priority.md`](planning/roadmap-priority.md) — 장기 우선순위 P0~P9
- [`planning/improvement-plan.md`](planning/improvement-plan.md) — 실측 기반 단기/전술 개선 계획

## Operations & Evaluation

- [`operations/benchmark.md`](operations/benchmark.md) — cost per successfully completed task benchmark
- [`operations/troubleshooting.md`](operations/troubleshooting.md) — 실제 운영 장애와 해결 기록

## Runtime Prompts

[`agents/`](agents/)는 문서 폴더처럼 보이지만 실제 Runtime system prompt에 로드되는 실행 정책이다.

- `agents/planner.md`
- `agents/coder.md`
- `agents/reviewer.md`
- `agents/debugger.md`
- `agents/chat.md`
- `agents/orchestrator.md`

**문서 정리 목적으로 이동하거나 수정하지 않는다.** 변경 시 Runtime behavior 변경으로 취급한다.

## Proposals

[`proposal/`](proposal/)은 외부 Harness/Agent 설계 분석과 아직 구현되지 않은 기능 제안을 보존한다.

- DeepSeek Harness adoption
- Claude Code clean-room adoption
- Hermes Agent adoption
- Tauri Desktop Host
- Web Search / Web Fetch
- Vision Agent

현재 반영 여부는 [`proposal/README.md`](proposal/README.md)를 본다.

## Archive

[`archive/`](archive/)는 초기 제품 명세 등 현재 문서와 역할이 겹치는 역사 기록이다. 현재 구현 판단에 사용하지 않는다.

## Directory Policy

```text
docs/
├─ README.md          # 문서 인덱스
├─ core/              # 현재 아키텍처·스펙·DB·Agent loop
├─ status/            # 구현 상태와 기능 matrix
├─ operations/        # benchmark·troubleshooting
├─ planning/          # roadmap·개선 계획
├─ agents/            # 실제 runtime prompt — 위치 유지
├─ proposal/          # 설계 제안/조사 기록
└─ archive/           # 더 이상 authoritative하지 않은 과거 문서
```

새 문서는 목적에 맞는 디렉터리에 추가하고 `docs/` 루트에 개별 문서를 늘리지 않는다.
