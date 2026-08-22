# FORGE Tauri Desktop Host 도입 제안

> 상태: Proposal
> 목표: 기존 FORGE Agent Harness를 유지하면서 macOS 로컬 설치형 Desktop App 제공

## 1. 목적

FORGE는 현재 FastAPI 기반 Agent Runtime과 Vue PWA를 중심으로 동작한다. 현재 구조의 장점은 Agent Runtime과 UI 분리, 모바일 PWA 원격 접속, 서버 기반 장시간 Agent 실행, DeepSeek API 기반 저비용 Harness, Docker/Host 실행 모드, PostgreSQL persistence, SSE 기반 실시간 상태 전달이다.

하지만 로컬 사용에서는 사용자가 직접 서버 프로세스와 환경을 관리해야 한다. 장기적으로는 다음 경험을 목표로 한다.

> FORGE.app 실행 → Workspace 선택 → Agent 사용

이를 위해 Tauri를 FORGE의 Desktop Host로 사용한다.

## 2. 핵심 원칙

Tauri 전환은 기존 FORGE를 다시 만드는 프로젝트가 아니다.

기존 구조인 `Vue PWA → FastAPI → AgentRuntime`을 유지한다.

역할 경계:

- Tauri = Desktop Host
- FastAPI = Agent Server
- AgentRuntime = Harness
- Vue = UI

Tauri는 Desktop Window, FastAPI lifecycle 관리, Native OS integration, Secure credential storage, Workspace selection, Notification, Auto start, Update를 담당한다.

## 3. 목표 아키텍처

```text
                 FORGE.app
                     │
        ┌────────────┴────────────┐
        │                         │
   Tauri / Rust                Vue UI
        │                         │
        │                  localhost API
        │                         │
        └────── FastAPI Sidecar ──┘
                     │
               AgentRuntime
                     │
        ┌────────────┼────────────┐
        │            │            │
     DeepSeek      Tools       Persistence
                     │
                Docker / Host
```

모바일 원격 기능은 유지한다.

```text
                   Mac
                    │
              FORGE Agent Core
                    │
        ┌───────────┴───────────┐
        │                       │
   Tauri Desktop             FastAPI
                                │
                           CF Tunnel
                                │
                           iPhone PWA
```

Desktop과 Mobile은 동일 Agent Runtime을 제어한다.

## 4. Tauri 책임

Tauri는 가능한 한 얇게 유지한다.

### Process Lifecycle

앱 실행:

```text
FORGE.app
→ backend 상태 확인
→ FastAPI sidecar 시작
→ health check
→ Vue UI 연결
```

앱 종료 시 Desktop window 종료와 Agent Runtime 종료를 동일하게 취급하지 않는다. 장시간 Agent가 실행 중이면 UI가 없어도 Runtime이 살아 있을 수 있는 구조를 지향한다.

## 5. FastAPI Sidecar

기존 Python backend를 최대한 유지하고 Tauri가 subprocess로 FastAPI server를 실행한다.

```text
FORGE.app
└─ forge-backend
   └─ FastAPI
      └─ AgentRuntime
```

Tauri와 backend 통신은 기존 HTTP/SSE API를 재사용한다. 새로운 IPC protocol은 만들지 않는다.

장점:

- 기존 PWA 유지
- 모바일 remote 유지
- backend 테스트 재사용
- Desktop과 Server architecture 통일

## 6. Backend Packaging

개발 환경에서는 Python/uvicorn/FastAPI를 그대로 사용한다.

배포 버전에서는 사용자가 별도 Python을 설치하지 않아도 되는 것이 목표다.

후보:

### A. Python runtime 포함

장점: 현재 backend 변경 최소.

단점: 앱 크기와 dependency 관리 부담.

### B. Backend executable

PyInstaller/Nuitka 등으로 backend를 standalone executable로 패키징한다.

```text
FORGE.app
└─ Contents
   └─ Resources
      └─ forge-backend
```

초기 PoC에서 빌드 크기, startup, subprocess 관리, SSE 호환성을 검증한 뒤 결정한다.

## 7. Workspace 관리

문자열 path 입력 대신 native folder picker를 제공한다.

```text
Workspace 추가
→ macOS Folder Picker
→ 사용자 선택
→ path backend 전달
```

향후 sandbox 정책과도 연결한다.

## 8. API Key 보안

Desktop에서는 OS credential storage를 사용한다.

- macOS: Keychain
- Windows: Credential Manager
- Linux: Secret Service

```text
Vue
→ Tauri Command
→ OS Secure Storage
```

API Key가 localStorage, DB, 로그, SSE에 노출되지 않아야 한다.

## 9. Native Notification

다음 상태에서 OS notification을 제공할 수 있다.

- 작업 완료
- 승인 필요
- 사용자 질문 필요
- 실패
- review_limit
- 장시간 작업 완료

Desktop notification과 향후 모바일 Push는 동일 Agent Event를 소비하는 구조를 지향한다.

## 10. Menu Bar Agent

향후 macOS menu bar 상주 모드를 고려한다.

```text
● FORGE

Running: 1
Waiting Approval: 0

Open FORGE
Pause Agent
Stop Agent
```

Desktop window를 닫아도 AgentRuntime을 유지할 수 있어야 한다.

## 11. Docker / Host 관계

Tauri 도입 때문에 Docker architecture를 제거하지 않는다.

```text
AgentRuntime
→ Execution Policy
   ├─ Docker Sandbox (기본)
   └─ Host Mode (명시적 opt-in)
```

Tauri는 실행 환경을 선택·표시하는 UI를 제공할 수 있다. 현재의 안전한 기본값은 유지한다.

## 12. Database

초기 Tauri 버전에서는 PostgreSQL 구조를 유지한다. Tauri 도입과 DB migration을 동시에 진행하지 않는다.

향후 standalone 배포가 중요해지면 별도 proposal에서 다음을 검토한다.

```text
Personal Mode → SQLite
Server Mode   → PostgreSQL
```

## 13. Remote Access

Tauri Desktop을 도입해도 모바일 PWA는 제거하지 않는다. 초기 구현에서는 기존 Cloudflare Tunnel 설정을 유지한다.

향후 Desktop에서 remote 상태를 관리하는 UX를 검토할 수 있다.

## 14. Desktop / Mobile 상태 동기화

Desktop과 Mobile이 동시에 접속할 수 있다.

```text
AgentRuntime / DB / Event Log
          ↓
       FastAPI
       ↙    ↘
  Desktop   Mobile
```

UI가 Agent 상태의 authoritative source가 되어서는 안 된다.

## 15. Durable Worker와 관계

Tauri process와 Agent process를 강하게 결합하지 않는다.

나쁜 구조:

```text
Tauri 종료 → Agent 종료
```

장기 목표:

```text
Tauri UI
   │
FORGE Supervisor
   │
Agent Worker
```

Durable Worker proposal과 Tauri proposal은 보완 관계다.

## 16. 성능 원칙

FORGE의 최상위 지표는 계속 `cost per successfully completed task`다.

Tauri는 UI/배포 계층이므로 LLM prompt, context, model routing, cache, tool loop 효율을 악화시키면 안 된다. Desktop idle CPU/RAM, backend startup latency도 측정한다.

## 17. 지원 플랫폼

우선순위:

1. macOS Apple Silicon
2. macOS Intel
3. Windows

Linux는 실제 수요가 있을 때 검토한다.

## 18. 단계별 구현

### Phase T0 — PoC

- Tauri project 생성
- 기존 Vue UI 연결
- FastAPI sidecar 실행
- health check
- SSE 테스트
- 앱 종료 처리

성공 조건:

```text
FORGE.app 실행
→ backend 자동 시작
→ 기존 채팅 화면 표시
→ Agent 작업 성공
```

### Phase T1 — Native Desktop

- Folder Picker
- Keychain
- Native Notification
- Window lifecycle
- backend process monitoring

### Phase T2 — Persistent Agent

- Menu Bar
- background Agent
- launch at login
- backend supervisor
- crash restart
- durable worker 연동

### Phase T3 — Remote Control

- Remote access 상태
- Cloudflare Tunnel integration 검토
- Desktop/Mobile 동시 연결
- mobile push

### Phase T4 — Distribution

- backend standalone packaging
- macOS signing
- notarization
- updater
- release artifact

## 19. 초기 작업에서 하지 않을 것

- AgentRuntime Rust 재작성
- FastAPI 제거
- Vue 제거
- PostgreSQL → SQLite migration
- Docker 제거
- 자체 IPC protocol 개발
- 모바일 PWA 제거
- 모든 OS 동시 지원
- Agent architecture 대규모 리팩터링

Desktop packaging 때문에 안정화된 Harness를 흔들지 않는다.

## 20. 주요 리스크

### Python Backend Packaging

가장 큰 기술 리스크다. 반드시 PoC로 먼저 검증한다.

### Process Lifecycle

Desktop 종료, background 유지, Agent 종료 정책을 명확히 해야 한다.

### Docker Dependency

일반 사용자 배포에서는 Docker 설치 요구가 진입장벽이 될 수 있다. 향후 Personal Mode에서 Host execution 또는 경량 sandbox를 별도 검토한다.

### Database Dependency

PostgreSQL 설치 요구 역시 standalone UX의 부담이지만 Tauri PoC와 동시에 해결하지 않는다.

## 21. 성공 기준

1. FORGE.app 하나로 backend 시작 가능
2. 별도 터미널 작업 불필요
3. 기존 AgentRuntime 변경 최소
4. 기존 PWA 유지
5. 모바일 원격 유지
6. 장시간 Agent 실행 가능
7. API Key 안전 저장
8. Workspace native 선택
9. 기존 Harness 성능 회귀 없음
10. Desktop 종료와 Agent lifecycle 분리 가능

## 22. 최종 방향

```text
              FORGE Agent Platform

                    Core
                     │
          ┌──────────┼──────────┐
          │          │          │
       Desktop     Mobile      API
        Tauri       PWA
          │          │
          └──── FastAPI ────────┘
                     │
               Agent Harness
                     │
       ┌─────────────┼─────────────┐
       │             │             │
    DeepSeek       Tools       Persistence
                      │
                ExecutionBackend
                 │           │
               Docker       Host
```

Tauri는 FORGE를 대체하지 않는다. FORGE Harness를 일반 사용자가 설치하고 실행할 수 있게 만드는 Desktop Host다.

가장 먼저 해야 할 것은 전체 Desktop 제품 개발이 아니라 **기존 Vue + FastAPI를 거의 수정하지 않고 Tauri에서 sidecar로 실행하는 T0 PoC**다.
