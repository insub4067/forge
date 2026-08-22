# FORGE Agentic Coding AI Product Specification

> Version 1.1 · 2026-08-22

## 1. Product Vision

FORGE는 AI에게 코드 한 번 써달라고 요청하는 도구가 아니라, 프로젝트를 맡아 **계획·실행·검토·수정·재검증**하는 셀프호스팅 Agent Runtime이다.

핵심 제품 차별점:

- DeepSeek Flash 중심의 저비용 반복 실행
- 복잡하거나 실패한 경우에만 Pro escalation
- Mac에서 장시간 실행
- 모바일 PWA에서 원격 지휘·승인·관찰
- context/cache/tool 비용을 계측하며 최적화
- 성공 경험을 Skill로 저장·재사용

최상위 제품 지표는 **cost per successfully completed task**다.

## 2. Workspace / Room

각 Chat Room은 하나의 명시적 local workspace와 연결된다.

```text
Room A → ~/Projects/trade-bot
Room B → ~/Projects/SmartBIMS
```

신규 방은 workspace 선택이 필수다. 파일 브라우저와 Agent Tool은 이 workspace를 작업 경계로 삼는다.

각 Room은 다음을 가진다.

- message history
- workspace path
- task/Kanban
- context/metrics
- selected/reusable Skills
- running/final status
- git checkpoint/history

## 3. Agent Workflow

```text
User Request
 ↓
Triage
 ↓
Planner
 ↓
Coder
 ↓
Reviewer
 ├─ all tasks done → Complete
 └─ defect → Debugger → Reviewer
```

Reviewer/Debugger loop는 최대 3회다. task 상태가 성공 판정의 authority다.

## 4. Model Strategy

FORGE는 강한 모델을 항상 쓰지 않는다.

- Planner: Flash + medium, COMPLEX만 Pro + high
- Coder: Flash
- Reviewer: Flash + medium
- Debugger: Flash, 마지막 복구만 Pro
- Chat/Triage: Flash
- Vision: Flash Vision

기본 원칙: **Flash-first, Pro-on-demand**.

## 5. Context / Cache

- provider 실측 prompt token 기준 pressure
- 75% 비파괴 compaction
- 95% 최후 hard block
- long tool result pruning
- stable system/role prefix
- cache hit/miss telemetry
- Skill은 관련 상위 항목만 선택 삽입

DB/history 원본과 모델에 보내는 projected surface는 분리한다.

## 6. Tool / Permission

Agent가 사용하는 주요 tool:

```text
read_file
list_dir
grep
write_file
edit_file
bash
ask_user
update_tasks
save_skill
```

write/edit/bash/save_skill은 승인 대상이다. mutation 전 git SHA checkpoint를 기록한다. 읽기 전용 다중 tool은 병렬 prefetch 가능하다.

## 7. Self-Correction / Learning

Reviewer는 결과를 task 상태로 검증하고 Debugger가 결함을 수정한 뒤 Reviewer가 재검증한다.

여러 단계로 성공했고 반복 가치가 있는 절차는 `save_skill`로 `.forge/skills/*.md`에 저장할 수 있다. 저장은 승인 게이트를 통과하며, 다음 요청에서는 관련 Skill만 선택해서 context에 주입한다.

## 8. Remote Experience

모바일 UI의 목적은 IDE 복제가 아니라 Agent 운영이다.

지원:

- 실시간 role/activity
- thinking/text/tool/diff
- approval/question
- runtime steering
- task/Kanban
- Git changes/history/branch
- file browser
- Skill viewer
- session metrics

SSE가 끊기면 `/status` polling으로 Mac에서 실행 중인 Agent 상태를 계속 확인한다.

## 9. Durability

현재:

- PostgreSQL history/task/agent telemetry
- `sessions.running`, `sessions.final_status`
- JSONL durable event/action log
- run crash 가시화
- 서버 재시작 시 interrupted run reconcile

미완료:

- worker process 독립화
- durable queue
- replayable authoritative event stream
- 프로세스 재시작 후 실제 run continuation

따라서 현재는 **reconnect-friendly persistent Agent**지만 완전한 crash-resumable execution engine은 아니다.

## 10. Observability / Efficiency

FORGE는 다음을 role/session 단위로 측정한다.

- input/output tokens
- cache hit/miss
- model/tool calls
- retries/compactions
- Pro calls
- elapsed
- selected skills
- final status
- estimated cost(가격 설정 시)

성공 기준의 기본값은 `final_status == completed`다.

## 11. Product Direction

우선순위:

1. 실제 benchmark로 비용/성공률 측정
2. durable worker + run resume
3. Tool Script/RPC로 model round-trip 감소
4. scheduler/condition jobs + push
5. Local/SSH/Docker execution backend
6. isolated subagent는 실익 검증 후 도입

FORGE는 거대한 agent framework를 만드는 것이 아니라 **작고 이해 가능한 Python runtime으로 높은 성공률/비용 효율을 만드는 것**을 목표로 한다.
