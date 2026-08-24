# FORGE Product / Runtime Specification

> Current-state spec. 역사적 v1 스펙은 `docs/archive/`에 보존한다.

## 1. Product Goal

FORGE는 사용자의 개발 환경에 상주하면서 **실제 일을 끝내고 그 완료를 증명하는 개인 개발 에이전트**다.

제품 경험 목표:

- 사용자는 자연어로 일을 맡긴다.
- Harness가 필요한 탐색/계획/구현/수리/검증을 끝까지 진행한다.
- 막히거나 위험 경계가 있을 때만 질문/승인을 요청한다.
- 모바일에서 진행·승인·steering·cancel·결과를 확인할 수 있다.
- 프로젝트 지식은 검증된 형태로 이어지되 conversation context는 무한 성장하지 않는다.

## 2. Quality Contract

최우선 불변식:

1. **모델 self-report는 completion authority가 아니다.**
2. 코드 변경 run은 사용자 요구사항을 Acceptance Gates로 표현한다.
3. gate 0인 코드 변경은 `completed` 불가.
4. Generic Verification은 passed/failed/unavailable을 구분한다.
5. Acceptance PASS는 실제 command + expected stdout evidence가 있어야 한다.
6. 최종 합쳐진 상태에서 Integration Verification을 수행한다.
7. fully verified 결과만 auto push한다.
8. 실패/미검증 이유를 숨기지 않는다.
9. Project Memory는 evidence/provenance validation을 통과해야 한다.
10. 현재 source/config가 memory/proposal보다 높은 authority를 가진다.

## 3. Runtime Modes

Room `mode`:

- auto(default): Triage가 chat/work 판정
- chat: read-only response
- work: coding path 강제

Coding topology는 Runtime이 자동 결정한다.

- simple: Developer
- complex: Planner → Developer → fresh Reviewer; Reviewer fail 시 Developer repair 1회

사용자가 multi/single topology를 직접 선택하는 UI/API는 현재 비목표다.

## 4. Model Policy

현재 provider는 DeepSeek only.

- Flash-first
- bounded Pro escalation
- Vision 요청은 vision model route
- 세션별 tier `auto/flash/pro`
- Planner/Reviewer/Gate Recovery는 비용을 억제한 Flash 경로

Provider independence는 향후 확장점이지 현재 기능이 아니다.

## 5. Tools / Security

Workspace path boundary, approval policy, dangerous command block, Docker sandbox를 유지한다. Host mode/host PTY/Mac input은 high-trust capability다.

`FORGE_AUTH_TOKEN` 설정 시 API/WebSocket과 uploads를 보호한다. Remote deployment는 별도 Zero Trust/VPN 경계도 사용한다.

## 6. Context

- logical budget 131072
- 75% compaction / 95% block
- compaction summary DB persistence
- selective Skills
- symbol-aware source reading
- recoverable tool-result pruning
- fresh Planner/Reviewer context
- task boundary에서 새 세션 + 동일 workspace 가능

Long-term project memory와 long conversation context를 분리한다.

## 7. Durability

- PostgreSQL history/session/task/gate/telemetry
- step-level save
- running/final status
- restart 후 headless Auto Resume
- resuming crash-loop guard
- persisted approval/model-tier policy
- JSONL event log

현재 Python coroutine/worker process 자체를 checkpoint에서 이어붙이는 event-sourced worker는 아니다. history/state에서 안전한 새 run으로 재구성하는 resume다.

## 8. Automation / Remote

- Scheduled one-shot/daily/interval jobs
- mobile job management/run-now
- Terminal: host PTY WebSocket
- Screen: polling preview + mouse/keyboard remote input
- Camera PoC
- MCP stdio high-level task facade

Condition/Deferred watcher, WebRTC screen, remote MCP transport는 아직 구현되지 않았다.

## 9. Evaluation

Primary metrics:

1. `verified_task_success_rate`
2. `false_completion_rate`
3. `human_interventions_per_task`
4. `repair_success_rate`
5. `cost_per_verified_task`
6. `elapsed_per_verified_task`

R0 25-task deterministic benchmark와 RSI promotion gate를 사용한다. 가격/속도 개선이 success-rate regression을 정당화하지 않는다.

## 10. Non-goals / Deferred

- agent 수 자체를 늘리는 것
- 기본 10-agent swarm
- provider 수를 KPI로 삼는 것
- LLM judge를 최종 correctness authority로 쓰는 것
- 검증 없는 자동 main merge
- 범용 automation SaaS/IDE/원격데스크톱 복제
- 대규모 plugin framework rewrite

## 11. Next Expansion Criteria

새 기능은 다음 질문을 통과해야 한다.

> “이 변경 때문에 사용자가 FORGE에 실제 일을 더 자주 맡기고, 확인/개입 부담이 줄어드는가?”

Provider abstraction, durable worker isolation, Condition Jobs, fresh workers, Tool RPC 모두 benchmark와 dogfooding evidence를 근거로 우선순위를 정한다.
