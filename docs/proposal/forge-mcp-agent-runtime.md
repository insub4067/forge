# FORGE MCP Server 확장 제안서

**작성일:** 2026-08-23  
**대상 프로젝트:** FORGE  
**목표:** FORGE를 독립적인 Agentic Coding Runtime에서 **외부 AI 에이전트가 호출할 수 있는 MCP 기반 Agent Runtime Server**로 확장한다.

> **선결(prerequisite):** MCP 서버는 얇은 Transport 레이어다. 그 아래 ①보안 경계(Policy Gateway·approval) ②Runtime Boundary 추상화 ③Durable Worker/Resume가 먼저다. 특히 durability는 §9가 못박듯 필수 — 자세한 설계는 [`durable-worker-resume.md`](durable-worker-resume.md).

---

## 1. 제안 요약

현재 FORGE는 단순한 LLM 래퍼가 아니다.

현재 구조는 다음과 같다.

```text
User Goal
   ↓
Triage
 ├─ CHAT
 ├─ SIMPLE → Coder → Reviewer
 └─ COMPLEX → Planner → Coder → Reviewer
                                ↓
                           Debugger ↔ Reviewer
```

여기에 파일 읽기/수정, grep, shell, build, Skills, approval, Docker sandbox, telemetry, PostgreSQL persistence 등이 이미 결합되어 있다.

따라서 FORGE의 MCP 전략은 단순히 **MCP Tools를 FORGE 내부에서 사용하는 것**에 그칠 필요가 없다.

FORGE 자체를 다음과 같이 노출한다.

```text
Claude / ChatGPT / Codex / IDE / Other Agent
                    │
                    │ MCP
                    ▼
            ┌────────────────┐
            │   FORGE MCP    │
            │     Server     │
            └───────┬────────┘
                    │
             Forge Agent API
                    │
          ┌─────────▼─────────┐
          │   Agent Runtime   │
          │                   │
          │ Triage            │
          │ Planner           │
          │ Coder             │
          │ Reviewer          │
          │ Debugger          │
          └─────────┬─────────┘
                    │
         ┌──────────▼──────────┐
         │ Tools / Skills /    │
         │ Sandbox / Workspace │
         └─────────────────────┘
```

즉 FORGE를 **“AI가 사용하는 AI 실행 엔진”**으로 만든다.

---

## 2. 왜 MCP Server인가

MCP의 일반적인 사용 형태는 다음과 같다.

```text
LLM
 ↓
MCP Client
 ↓
MCP Server
 ↓
Database / GitHub / Files / API
```

FORGE에서는 이를 한 단계 올릴 수 있다.

```text
LLM
 ↓
MCP Client
 ↓
FORGE
 ↓
Agent Loop
 ↓
Tools
 ↓
실제 코드 변경
```

기존 MCP Tool은 대체로 **단일 액션**을 수행한다.

예:

```text
read_file()
query_database()
create_issue()
run_test()
```

반면 FORGE Tool은 다음과 같은 **목표 단위 작업**을 수행할 수 있다.

```text
forge.execute(
    goal="로그인 버그를 찾아 수정하고 테스트까지 완료"
)
```

내부에서는:

```text
Triage
  ↓
Planning
  ↓
Search
  ↓
Code modification
  ↓
Tests
  ↓
Review
  ↓
Debug
  ↓
Final result
```

가 실행된다.

이것이 FORGE를 일반 MCP Server와 구분하는 핵심이다.

---

## 3. MCP와 FORGE의 적합성

최신 MCP는 long-running agent 작업을 다루기 위한 task-oriented execution 모델과 authorization 강화 방향으로 발전하고 있다.

이는 FORGE와 상당히 잘 맞는다.

FORGE 작업은 본질적으로 다음처럼 수 초가 아니라 수십 초~수분 이상 걸릴 수 있다.

```text
tools/call
    ↓
Forge Task 생성
    ↓
task_id 반환
    ↓
Agent Loop 실행
    ↓
status 조회
    ↓
progress / state
    ↓
result
```

따라서 FORGE는 일반 Tool Server보다 **Task-oriented MCP Server**에 가깝게 설계하는 것이 적합하다.

---

## 4. 핵심 설계 원칙

### 4.1 FORGE 내부 구조는 유지한다

MCP 때문에 기존 Agent Runtime을 다시 작성하지 않는다.

```text
┌───────────────────────┐
│     Transport Layer   │
│                       │
│ REST / SSE / MCP      │
└──────────┬────────────┘
           │
┌──────────▼────────────┐
│ Forge Application API │
└──────────┬────────────┘
           │
┌──────────▼────────────┐
│    Agent Runtime      │
└───────────────────────┘
```

MCP는 새로운 **Transport / Integration Layer**다.

---

## 5. 제안 MCP Tools

초기 버전은 Tool 수를 최소화한다.

### 5.1 `forge_execute`

가장 중요한 Tool.

```text
forge_execute(
    goal,
    workspace,
    mode,
    constraints
)
```

예:

```json
{
  "goal": "API 로그인 오류를 분석하고 수정한 뒤 테스트해",
  "workspace": "/projects/app",
  "mode": "autonomous"
}
```

내부:

```text
Triage
 ↓
Planner
 ↓
Coder
 ↓
Reviewer
 ↓
Debugger
```

반환:

```json
{
  "task_id": "forge_xxx",
  "status": "running"
}
```

### 5.2 `forge_status`

```text
forge_status(task_id)
```

반환 예:

```json
{
  "status": "review",
  "progress": 78,
  "current_step": "Running unit tests",
  "cost": 0.0132
}
```

### 5.3 `forge_result`

```text
forge_result(task_id)
```

결과:

```text
changed_files
summary
tests
review_result
cost
token_usage
```

### 5.4 `forge_cancel`

```text
forge_cancel(task_id)
```

장시간 실행 Agent 작업 중단.

---

## 6. 두 번째 단계 Tools

기본 agent execution이 안정화되면 다음 기능을 추가한다.

```text
forge_review
forge_debug
forge_plan
forge_inspect_repository
forge_run_tests
```

예:

```text
forge_review(
   goal="이 PR의 race condition 가능성을 검토"
)
```

이 경우 전체 coding loop가 아니라 Reviewer만 사용할 수 있다.

---

## 7. Resources

MCP Resources도 활용할 수 있다.

```text
forge://workspace/{id}
forge://task/{id}
forge://task/{id}/events
forge://task/{id}/diff
forge://skills
forge://metrics
```

예:

```text
forge://task/abc123/diff
```

외부 Agent가 FORGE의 작업 결과를 다시 읽고 판단할 수 있다.

---

## 8. FORGE Skills와 MCP

FORGE의 Curated / Learned / Project 3계층 Skill 구조는 MCP Resource로 자연스럽게 연결할 수 있다.

```text
forge://skills
forge://skills/systematic-debugging
```

또한 이후에는 다음과 같은 도구도 제공 가능하다.

```text
forge_search_skills
```

이렇게 하면 외부 Agent가 FORGE의 **학습된 procedural knowledge**까지 활용할 수 있다.

---

## 9. 가장 중요한 구조 변화: Durable Execution

FORGE의 주요 미완성 기능 중 하나는 다음이다.

> Durable Worker + authoritative event replay for true restart continuation

MCP를 통해 외부 Agent가 FORGE에게 장기 작업을 위임하면 다음 상황이 반드시 발생한다.

```text
Claude
 ↓
forge_execute
 ↓
FORGE
 ↓
5분 작업

서버 restart
```

작업이 사라지면 MCP Agent Runtime으로 사용할 수 없다.

따라서 다음 구조가 필요하다.

```text
MCP Server
    │
    ▼
Task Queue
    │
    ▼
Forge Worker
    │
    ├─ checkpoint
    ├─ event log
    └─ state persistence
```

서버 재시작 후:

```text
task_id
 ↓
checkpoint load
 ↓
resume
```

가 가능해야 한다.

---

## 10. MCP Task와 Forge Task 통합

Forge 내부 Task를 MCP Task와 1:1 대응시키는 것을 권장한다.

```text
MCP Task
    │
    ▼
Forge Task
    │
    ▼
Agent Run
```

상태:

```text
queued
planning
coding
reviewing
debugging
completed
failed
cancelled
```

기존 `update_tasks`의 상태 모델을 확장해 적용할 수 있다.

---

## 11. Approval 설계

이 부분은 매우 중요하다.

현재 FORGE는 write/edit/bash/save_skill 등 위험도가 높은 Tool을 approval 대상으로 둔다.

MCP를 추가한다고 이 정책을 우회해서는 안 된다.

잘못된 구조:

```text
Claude
 ↓
MCP
 ↓
bash directly
```

권장 구조:

```text
Claude
 ↓
MCP
 ↓
Forge Agent
 ↓
Policy Gateway
 ↓
Approval
 ↓
Sandbox
```

MCP는 **Forge security boundary 밖에 존재하면 안 된다.**

---

## 12. 저수준 내부 Tool을 그대로 공개하지 않는다

FORGE 내부의 다음 Tool을 MCP로 직접 노출하는 방식은 추천하지 않는다.

```text
read_file
list_dir
grep
write_file
edit_file
bash
build_frontend
```

이를 전부 공개하면 FORGE는 사실상 remote shell/filesystem MCP가 된다.

FORGE의 가치는 Agent Runtime 자체에 있으므로 MCP에는 **high-level capability**만 제공한다.

```text
forge_execute
forge_review
forge_debug
forge_plan
```

내부 low-level Tool은 Agent Runtime 전용으로 유지한다.

---

## 13. 보안

MCP Server가 추가되면 FORGE의 공격 표면은 크게 증가한다.

특히 FORGE는 filesystem write, Git, shell, Host Terminal, Screen, Camera 등 로컬 시스템 자원에 접근할 수 있으므로 Remote MCP에는 반드시 인증과 정책 경계가 필요하다.

권장 구조:

```text
Internet
   │
Cloudflare Access
   │
OAuth / Token
   │
Forge MCP Gateway
   │
Policy Engine
   │
Forge Runtime
```

추가적으로 다음을 둔다.

```text
workspace allowlist
tool policy
command policy
task quota
rate limit
audit log
```

---

## 14. MCP Transport

신규 FORGE MCP 구현은 오래된 SSE-only 예제에 과도하게 결합하지 않는다.

권장:

```text
Local
 └─ stdio

Remote
 └─ HTTP-based MCP transport
```

장기적으로는:

```text
stateless MCP endpoint
        │
        ▼
Forge durable task store
```

로 분리한다.

프로토콜 transport는 stateless에 가깝게 유지하더라도 Forge application state는 stateful하게 유지한다.

---

## 15. 예상 활용 방식

### Claude / ChatGPT / Codex

```text
사용자:
Forge를 이용해서 이 프로젝트의 로그인 버그를 고쳐.
```

상위 Agent:

```text
forge_execute()
```

FORGE:

```text
Planner
Coder
Reviewer
Debugger
```

상위 Agent는 결과와 진행상태만 전달받는다.

### IDE Agent

```text
IDE Agent
   ↓
Forge MCP
   ↓
long-running delegated task
```

IDE Agent는 작은 수정에 집중하고 FORGE에 큰 작업을 위임할 수 있다.

---

## 16. 핵심 차별점

일반 MCP Server:

```text
Agent → Tool
```

FORGE MCP:

```text
Agent → Agent Runtime → Tools
```

즉 FORGE의 포지션은:

> **MCP-accessible autonomous execution runtime**

이다.

좀 더 단순하게 표현하면:

> **Agent for Agents**

가 된다.

---

## 17. 구현 구조 제안

```text
backend/app/

mcp/
 ├─ server.py
 ├─ tools.py
 ├─ resources.py
 ├─ auth.py
 └─ task_adapter.py

runtime/
 ├─ agent_runtime.py
 ├─ task_manager.py
 ├─ checkpoint.py
 └─ worker.py

policy/
 ├─ approval.py
 ├─ workspace.py
 └─ capabilities.py
```

핵심 인터페이스:

```python
class ForgeRuntime:
    async def execute(self, request) -> TaskHandle:
        ...

    async def status(self, task_id) -> TaskStatus:
        ...

    async def result(self, task_id) -> TaskResult:
        ...

    async def cancel(self, task_id) -> None:
        ...
```

FastAPI와 MCP가 모두 이것을 호출한다.

```text
FastAPI ─┐
         ├── ForgeRuntime
MCP ─────┘
```

---

## 18. 개발 우선순위

### P0 — Runtime Boundary

기존 Agent Runtime을 UI/API에서 분리한다.

```text
ForgeRuntime
TaskHandle
TaskResult
```

를 정의한다.

### P0 — Security Gateway

Tool execution 앞에 단일 policy boundary를 둔다.

```text
Agent
 ↓
Policy
 ↓
Approval
 ↓
ExecutionBackend
```

MCP/REST/Automation이 동일 정책을 사용하도록 한다.

### P1 — Durable Worker

```text
queue
checkpoint
event replay
resume
cancel
```

구현.

이 단계가 FORGE MCP Server의 실질적인 기반이다.

### P1 — MCP Server

최초 Tool은 4개만 구현한다.

```text
forge_execute
forge_status
forge_result
forge_cancel
```

### P1 — MCP Task Integration

Forge Task lifecycle과 MCP Task lifecycle을 연결한다.

### P2 — Resources

```text
workspace
task
diff
logs
skills
metrics
```

노출.

### P2 — Capability Tools

```text
forge_review
forge_debug
forge_plan
```

추가.

### P3 — Agent Federation

장기적으로:

```text
Claude
 ├─ Forge A
 ├─ Forge B
 └─ Forge C
```

혹은:

```text
Forge
 ├─ Mac Worker
 ├─ Linux Worker
 └─ GPU Worker
```

같은 실행 인프라 확장도 가능하다.

---

## 19. 하지 말아야 할 것

초기 버전에서 다음은 피한다.

### 모든 내부 Tool을 MCP로 공개

```text
bash
write_file
edit_file
```

직접 노출 금지.

### MCP 때문에 Agent Runtime 재작성

기존 Forge loop를 유지한다.

### Multi-Agent부터 구현

먼저:

```text
Durability
Security
Evaluation
```

을 해결한다.

### MCP Client 구현에만 집중

FORGE는 다른 MCP를 소비하는 기능도 필요하지만 차별화 가능성이 더 큰 부분은 **FORGE 자체를 MCP Server로 제공하는 것**이다.

---

## 20. 최종 목표 구조

```text
                    AI Ecosystem
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
    ChatGPT           Claude            IDE Agent
       │                 │                 │
       └──────────────── MCP ──────────────┘
                         │
                 ┌───────▼───────┐
                 │   FORGE MCP   │
                 │    Gateway    │
                 └───────┬───────┘
                         │
                  Policy / Auth
                         │
                 ┌───────▼───────┐
                 │ Forge Runtime │
                 └───────┬───────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
     Planner           Coder          Reviewer
        │                │                │
        └──────────── Debugger ───────────┘
                         │
                  ExecutionBackend
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       Docker           Host          Remote
          │
          ▼
      Workspace
```

---

## 21. 결론

FORGE의 MCP 지원을 단순한 **“MCP 기능 추가”**로 정의하면 안 된다.

핵심 방향은:

> **FORGE를 MCP를 통해 호출 가능한 autonomous execution runtime으로 만든다.**

이다.

FORGE는 이미 Agent Loop, Tool execution, Skills, approval, sandbox, telemetry, persistence를 가지고 있기 때문에 MCP Server를 위한 기반은 상당 부분 존재한다.

필요한 핵심 작업은 새로운 Agent를 더 만드는 것이 아니라:

```text
Runtime abstraction
        ↓
Security boundary
        ↓
Durable execution
        ↓
MCP Task integration
        ↓
MCP Server
```

순서로 시스템 경계를 정리하는 것이다.

이 구조가 완성되면 FORGE는 더 이상 단순한 self-hosted coding agent가 아니다.

**Claude, ChatGPT, IDE Agent 및 다른 Agent들이 로컬/사설 인프라의 코드 작업을 위임할 수 있는 범용 Agent Execution Runtime**이 된다.

장기적으로 FORGE의 가장 강력한 포지셔닝은 다음 문장으로 정리할 수 있다.

> **FORGE — The self-hosted execution runtime for AI agents.**
