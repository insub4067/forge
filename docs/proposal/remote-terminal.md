# Secure Remote Terminal 도입 제안

> 상태: Proposal  
> 목표: FORGE 사용자가 Agent가 작업하는 동일한 실행 환경에 안전하게 접속하여 관찰, 검증, 수동 복구할 수 있는 원격 터미널을 제공한다.

## 1. 배경

FORGE Agent는 이미 shell/tool을 사용해 repository를 탐색하고 테스트와 명령을 실행할 수 있다.

하지만 사용자는 Agent가 작업하는 환경에 직접 개입하려면 별도의 SSH/터미널을 열어야 한다.

특히 모바일 원격 사용에서는 다음이 불편하다.

- Agent가 실행한 명령을 직접 확인하기 어렵다.
- 실패한 프로세스를 사용자가 즉시 조사하기 어렵다.
- 간단한 명령 하나를 실행하기 위해 별도 원격 데스크톱/SSH가 필요하다.
- 장시간 실행 중인 프로세스를 관찰하거나 제어하기 어렵다.
- Agent 작업과 사용자의 수동 작업 환경이 분리된다.

따라서 FORGE에 Agent Harness와 연결된 제한형 Remote Terminal을 추가하는 것을 제안한다.

---

## 2. 핵심 원칙

FORGE Terminal은 일반적인 공개 Web Shell이 아니다.

> **Agent가 사용하는 ExecutionBackend에 사용자가 명시적으로 접속하는 운영/개입 인터페이스**다.

초기 구조:

```text
Vue / PWA
    ↓
 xterm.js
    ↓ WebSocket
 FastAPI
    ↓
PTY Session Manager
    ↓
ExecutionBackend
    ↓
Docker Sandbox
```

초기 버전은 Docker Sandbox만 지원한다.

Host Terminal은 보안 검증 이후 별도 opt-in 기능으로 추가한다.

---

## 3. PTY가 필요한 이유

단순 `subprocess.run()` 또는 기존 bash tool을 UI에 노출하는 방식으로 구현하지 않는다.

터미널은 interactive process를 지원해야 한다.

예:

- shell
- top
- git interactive command
- npm/pnpm dev server
- Python REPL
- test watcher
- interactive CLI

따라서 backend에서 PTY(Pseudo Terminal)를 생성하고 WebSocket으로 stdin/stdout을 전달한다.

```text
Keyboard
  ↓
WebSocket
  ↓
PTY stdin

PTY stdout
  ↓
WebSocket
  ↓
xterm.js
```

---

## 4. 초기 범위

Terminal v1은 작게 시작한다.

지원:

- Docker sandbox terminal
- workspace 기준 working directory
- interactive shell
- terminal resize
- UTF-8
- ANSI color
- Ctrl+C 등 기본 control sequence
- session reconnect
- idle timeout
- 명시적 session 종료

초기 미지원:

- Host shell
- arbitrary SSH target
- tmux replacement
- 파일 업로드/download
- terminal sharing
- 여러 사용자 공동 terminal
- browser automation

---

## 5. Session 모델

각 Terminal은 독립된 session ID를 가진다.

예:

```text
TerminalSession
- id
- user/session owner
- workspace_id
- execution_backend
- cwd
- created_at
- last_activity_at
- status
- process/pty handle
```

API 예:

```text
POST   /api/terminals
GET    /api/terminals
GET    /api/terminals/{id}
DELETE /api/terminals/{id}
WS     /api/terminals/{id}/ws
```

정확한 endpoint는 현재 API convention에 맞춰 구현 시 결정한다.

---

## 6. Workspace Boundary

Terminal은 반드시 하나의 workspace에 귀속된다.

초기 Docker mode에서는 해당 workspace가 mount된 sandbox에서 shell을 시작한다.

```text
Workspace
   ↓
Docker Sandbox
   ↓
PTY
```

사용자가 다른 workspace를 선택하면 별도 terminal session을 생성한다.

Terminal이 workspace boundary를 우회하는 통로가 되어서는 안 된다.

---

## 7. Agent Execution과의 관계

장기적으로 중요한 목표는 **Agent와 사용자가 동일한 ExecutionBackend를 볼 수 있게 하는 것**이다.

```text
             ExecutionBackend
              /            \
         Agent Tools      Terminal
```

예를 들어 Agent가 Docker sandbox에서 테스트 서버를 실행했다면 사용자가 같은 환경의 Terminal에서 상태를 확인할 수 있어야 한다.

다만 Agent tool call과 사용자 terminal input을 동일 프로세스 stdin에 무조건 연결하지 않는다.

Agent command execution과 interactive terminal session은 독립된 PTY/process를 사용하되 동일 filesystem/workspace 상태를 공유하는 방향으로 시작한다.

---

## 8. Human Takeover

Terminal의 가장 큰 가치는 Agent 실패 시 수동 개입이다.

예:

```text
Agent
→ test 실패
→ Debugger 반복 실패
→ 사용자 개입 요청

사용자
→ Terminal 열기
→ 직접 상태 확인
→ 수정/명령 실행
→ Agent에게 다시 작업 요청
```

향후 다음 UX를 검토한다.

```text
[터미널에서 확인]
[Agent에게 다시 넘기기]
```

사용자의 수동 변경 이후 Agent는 repository 상태를 다시 읽고 계속 작업한다.

Terminal transcript 전체를 자동으로 Agent context에 넣지는 않는다.

필요한 경우 사용자가 명시적으로 일부 결과를 전달하거나 Harness가 제한된 summary를 생성한다.

---

## 9. Frontend

초기 frontend는 `xterm.js` 사용을 우선 검토한다.

Desktop:

```text
┌─────────────────────────────┐
│ Terminal             +  ×   │
├─────────────────────────────┤
│ $ git status                │
│                             │
│                             │
└─────────────────────────────┘
```

모바일에서는 IDE 전체를 재현하려 하지 않는다.

핵심 UX:

- 터미널 전체 화면
- 큰 touch target
- Ctrl/Esc/Tab 등 보조 키 toolbar
- 명령 history 접근
- terminal reconnect
- landscape 대응

기존 Chat UI와 독립 route/tab로 둔다.

---

## 10. WebSocket

SSE는 server → client 단방향이므로 interactive terminal에는 적합하지 않다.

Terminal은 WebSocket을 사용한다.

메시지 유형 예:

```json
{"type":"input","data":"ls\n"}
{"type":"resize","cols":100,"rows":30}
{"type":"ping"}
```

Server → Client:

```json
{"type":"output","data":"..."}
{"type":"exit","code":0}
{"type":"error","message":"..."}
```

실제 binary/text framing은 PoC에서 성능을 확인한 뒤 결정한다.

---

## 11. Reconnect

모바일 환경에서는 WebSocket 연결이 자주 끊길 수 있다.

따라서 WebSocket connection lifecycle과 PTY lifecycle을 분리한다.

나쁜 구조:

```text
WebSocket disconnect
→ PTY kill
```

목표:

```text
WebSocket disconnect
→ PTY 유지
→ grace period
→ client reconnect
→ session 재연결
```

idle timeout 또는 명시적 종료 시 PTY를 제거한다.

출력 replay가 필요하면 작은 bounded ring buffer를 사용한다.

무제한 terminal transcript를 memory에 보관하지 않는다.

---

## 12. Security

Remote Terminal은 FORGE에서 가장 위험도가 높은 기능 중 하나다.

사실상 remote shell capability이므로 기본 보안 정책을 강하게 적용한다.

### 기본 정책

- Docker Sandbox only
- authenticated session 필요
- workspace-bound
- session ownership 검증
- idle timeout
- max session count
- audit event
- WebSocket origin 검증
- request size 제한
- rate limit 검토

FORGE instance 자체를 Public Internet에 직접 노출하지 않는다.

Cloudflare Tunnel만으로 authorization이 제공되는 것은 아니다.

Remote 사용 시 Cloudflare Zero Trust / Access, VPN, Tailscale 등 별도 접근 통제를 강하게 권장한다.

---

## 13. Host Terminal

초기 버전에서는 제공하지 않는다.

향후 지원한다면 반드시 명시적 opt-in이어야 한다.

예:

```text
ENABLE_HOST_TERMINAL=false
```

활성화 시 UI에 명확한 위험 경고를 표시한다.

> Host Terminal grants remote shell access to the machine running FORGE.

가능하면 FORGE process와 동일 OS user보다 제한된 별도 user/permission model을 검토한다.

Host Terminal을 활성화했다고 해서 기존 Agent approval policy가 자동으로 적용된다고 가정하면 안 된다.

사용자가 terminal에서 직접 실행하는 명령은 Agent tool call과 다른 trust boundary다.

---

## 14. Audit

최소 다음 event를 기록한다.

- terminal created
- connected
- disconnected
- reconnected
- resized
- terminated
- idle timeout
- backend/workspace

명령 전체를 기본 audit log에 평문 저장하는 것은 신중해야 한다.

명령에 token/password 등 secret이 포함될 수 있기 때문이다.

기본은 session metadata 중심으로 기록하고 full transcript 저장은 하지 않는다.

---

## 15. Secret 처리

Terminal 출력에는 credential이 나타날 수 있다.

따라서:

- terminal output을 LLM context에 자동 삽입하지 않는다.
- telemetry에 stdout/stderr 전체를 저장하지 않는다.
- full transcript를 DB에 기본 저장하지 않는다.
- client-side persistent storage에 transcript를 남기지 않는다.

향후 transcript 저장 기능이 필요하면 opt-in + secret redaction을 별도 설계한다.

---

## 16. Durable Worker와의 관계

Terminal 자체가 Durable Worker를 대체하지 않는다.

```text
Control Plane
├─ Durable Agent Worker
└─ Terminal Session Manager
        ↓
   ExecutionBackend
```

두 기능 모두 ExecutionBackend를 공유할 수 있지만 lifecycle은 독립적이다.

Agent Worker가 재시작되더라도 Terminal session 정책을 별도로 적용한다.

---

## 17. ExecutionBackend와의 관계

장기적으로 Terminal이 backend 구현을 직접 알지 않게 한다.

```text
TerminalSessionManager
        ↓
ExecutionBackend
├─ DockerBackend
├─ LocalBackend
└─ SSHBackend (future)
```

하지만 Terminal proposal 때문에 ExecutionBackend abstraction 전체를 먼저 과설계하지 않는다.

v1은 현재 Docker 실행 구조에 최소한으로 연결한다.

---

## 18. 성능 / Resource 제한

Terminal 하나가 무제한 resource를 소비하면 안 된다.

검토할 제한:

- 최대 동시 terminal 수
- idle timeout
- output buffer 크기
- WebSocket message 크기
- container resource policy

예시 초기값은 구현/benchmark에서 결정하고 magic number를 proposal에서 고정하지 않는다.

---

## 19. 단계별 구현

### Phase T0 — PTY PoC

- backend PTY 생성
- WebSocket stdin/stdout
- resize
- shell exit 처리
- 단일 Docker sandbox

성공 조건:

```text
PWA
→ Terminal 열기
→ ls/git status 실행
→ interactive command 동작
```

### Phase T1 — Session Lifecycle

- session ID
- reconnect
- bounded output buffer
- idle timeout
- explicit close
- workspace binding

### Phase T2 — Mobile UX

- xterm.js
- fullscreen terminal
- mobile key toolbar
- orientation/resize
- reconnect UX

### Phase T3 — Harness Integration

- Agent와 동일 workspace/backend
- failure 화면에서 Terminal 진입
- terminal 작업 후 Agent resume UX
- audit/telemetry

### Phase T4 — Host Mode 검토

보안 검토와 실제 수요가 확인된 뒤 진행한다.

---

## 20. 테스트

필수 테스트:

1. workspace boundary
2. WebSocket 인증 실패
3. 다른 사용자의 session 접근 차단
4. PTY resize
5. Ctrl+C
6. process exit
7. WebSocket disconnect/reconnect
8. idle timeout
9. output flood
10. container 종료
11. mobile background/foreground
12. UTF-8/한글 입력
13. ANSI escape sequence
14. 여러 terminal session

보안 테스트:

- path escape
- unauthorized websocket
- origin bypass
- session ID guessing
- oversized message
- resource exhaustion

---

## 21. 완료 기준

1. 사용자가 PWA에서 Docker sandbox terminal을 열 수 있다.
2. interactive PTY가 정상 동작한다.
3. Terminal과 Agent가 동일 workspace filesystem을 볼 수 있다.
4. WebSocket이 끊겨도 일정 시간 PTY가 유지된다.
5. 재접속할 수 있다.
6. workspace/session authorization을 우회할 수 없다.
7. terminal output이 자동으로 LLM context에 들어가지 않는다.
8. transcript가 기본적으로 영구 저장되지 않는다.
9. idle/resource 제한이 존재한다.
10. Host machine shell은 기본적으로 노출되지 않는다.

---

## 22. 하지 않을 것

초기에는 다음을 하지 않는다.

- VS Code Web 대체
- SSH client 플랫폼 구축
- tmux 완전 대체
- multi-user collaborative terminal
- terminal recording 서비스
- arbitrary host shell 공개
- browser에서 root shell 제공
- terminal transcript 전체를 Agent memory로 저장

FORGE Terminal의 목적은 IDE를 다시 만드는 것이 아니다.

> **Agent를 관찰하고, 필요한 순간 사람이 직접 개입하고, 다시 Agent에게 작업을 넘길 수 있게 하는 것**이다.

---

## 결론

Remote Terminal은 단순 편의 기능보다 Harness 운영 기능에 가깝다.

FORGE의 강점인 모바일 원격 제어와 결합하면:

```text
Agent 실행
→ 모바일에서 상태 확인
→ 문제 발생
→ Terminal 직접 개입
→ 상태 복구
→ Agent 재개
```

흐름을 만들 수 있다.

초기 구현은 반드시 **Docker Sandbox + PTY + WebSocket + Workspace Boundary**로 제한한다.

보안과 lifecycle이 검증된 뒤에만 Host Terminal로 확장한다.
