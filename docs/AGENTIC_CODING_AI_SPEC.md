# Forge Agentic Coding AI Product Specification v1.0

## 1. Overview

Forge는 단순한 AI 코딩 채팅 도구가 아닌 사용자의 요구사항을 분석하고 계획을 수립하며 실제 개발 작업을 수행하는 Agentic Coding AI Harness를 목표로 한다.

핵심 목표:

- 사용자 요구사항 분석
- 작업 계획(Plan) 생성
- TODO 기반 Task 관리
- 코드 실행 및 검증
- 진행 상황의 투명한 UI 제공

---

## 2. Chat Room Based Workspace

### Requirement

사용자는 여러 개의 Chat Room을 생성할 수 있어야 한다.

각 Chat Room은 독립적인 작업 공간(Workspace)과 연결된다.

Example:

```
Chat Room: Trade Bot
Workspace: ~/Projects/trade-bot

Chat Room: SmartBIMS
Workspace: ~/Projects/SmartBIMS
```

Chat Room은 다음 정보를 관리한다.

- 대화 기록
- Workspace 경로
- 프로젝트 Context
- Agent 실행 상태
- Task 목록

---

## 3. Workspace Model

```json
{
  "id": "chat_001",
  "name": "Trade Bot Development",
  "workspace_path": "~/Projects/trade-bot",
  "status": "active"
}
```

Workspace는 Agent가 접근하는 실제 로컬 프로젝트 폴더이다.

---

## 4. Agent Workflow

사용자의 요청은 즉시 코드 변경으로 이어지지 않는다.

Flow:

```
User Request
      ↓
Requirement Analysis
      ↓
Repository Analysis
      ↓
Planning Agent
      ↓
Task Generation
      ↓
Execution Agent
      ↓
Review / Validation
      ↓
Result Report
```

---

## 5. Planning System

Agent는 작업 전 실행 계획을 생성한다.

Example:

```
Goal:
로그인 기능 개선

Tasks:
1. 인증 구조 분석
2. API Layer 확인
3. Token Refresh 구현
4. 테스트 작성
5. 검증
```

사용자는 실행 전 Plan을 확인할 수 있다.

---

## 6. Task Management

모든 Agent 작업은 Task 단위로 관리한다.

Task Status:

```
TODO
 ↓
PLANNING
 ↓
IN_PROGRESS
 ↓
REVIEW
 ↓
DONE
```

Task Example:

```json
{
  "title": "Implement Token Refresh",
  "status": "in_progress",
  "progress": 60
}
```

---

## 7. Progress UI

사용자는 Agent의 현재 작업 상태를 확인할 수 있어야 한다.

Example:

```
Project: Trade Bot

Completed
✓ Analyze strategy engine
✓ Review risk manager

Running
▶ Add stop loss rule

Pending
○ Write tests
○ Run simulation

Progress: 70%
```

---

## 8. Execution Transparency

Agent는 모든 작업 로그를 기록한다.

Example:

```
12:01 Analyze repository
12:05 Create implementation plan
12:10 Modify risk.py
12:15 Run tests
12:20 Validation completed
```

---

## 9. Architecture Direction

```
                 Web UI / PWA
                      |
                 FastAPI Server
                      |
             Agent Orchestrator
          /          |           \
 Planner Agent  Coding Agent  Review Agent
                      |
              Workspace Manager
                      |
             Local File System
```

---

## 10. Product Vision

Forge의 목표는 AI에게 코드를 작성시키는 도구가 아니다.

AI 개발자가 하나의 프로젝트를 맡아 수행하는 환경을 만드는 것이다.

사용자는 목표를 제시하고 Agent는:

- 프로젝트 이해
- 계획 수립
- 작업 분해
- 코드 작성
- 테스트
- 결과 보고

까지 수행한다.

---

Version: 1.0
Date: 2026-08-22
