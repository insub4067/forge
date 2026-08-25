# FORGE Architecture

> 2026-08-24 현재 `main` source 기준.

## 1. Product Boundary

FORGE는 범용 Agent OS가 아니라 **self-hosted verified coding runtime**이다.

```text
Mobile/Desktop Browser
        ↓ HTTP/SSE/WebSocket
Vue 3 PWA
        ↓
FastAPI Control Plane
        ↓
AgentRuntime
├─ routing / role loop
├─ context / memory / skills
├─ approval / cancellation / budget
├─ verification / completion
└─ telemetry / refinement
        ↓
Tools / DockerSandbox / Git / Host capabilities
        ↓
Local workspace
```

PostgreSQL이 history/session/task/gate/job/telemetry의 durable store이고 JSONL event log가 실행 관측을 보조한다.

## 2. Frontend

Vue 3 + Vite PWA. UI는 Agent lifecycle의 authority가 아니다.

주요 UX:

- rooms/workspaces, chat/work mode
- SSE/polling 기반 진행 상태
- 상단 activity card 하나로 reasoning/tool/verification 상태 표시
- 하단 task-bar 하나로 현재 task 진행 표시
- approval/question/cancel/steering
- Files/Git/Skills/Metrics/Kanban
- Scheduled Jobs
- Mac: Terminal/Screen/Camera

방별 `auto_approve`와 `model_tier`는 서버 값을 authority로 사용한다. localStorage는 신규 세션 기본값 정도로만 사용한다.

## 3. Control Plane

FastAPI는 REST/SSE/WebSocket, session state, file upload, scheduler, Mac remote endpoints를 제공한다.

- `FORGE_AUTH_TOKEN`이 설정되면 `/api/*`(health 제외)와 `/uploads/*`를 보호한다.
- CORS는 현재 `*`이므로 remote deployment에서는 네트워크 접근제어와 app token을 함께 사용한다.
- startup에서 idempotent DB schema patch 후 interrupted run resume와 scheduler를 시작한다.

## 4. AgentRuntime

한 Runtime이 core execution contract를 가진다.

### Route

`chat/work/auto` room mode. auto는 Triage 사용.

### Roles

- Chat: read-only
- Planner: complex 요청에서만, read-only/fresh
- Developer: 유일한 mutation executor
- Reviewer: complex 요청에서만, fresh independent review
- Gate Recovery: gate 누락 안전망

Multi/single을 사용자가 직접 고르는 UI/API는 현재 없다.

### Verification

- Generic test/build/runtime smoke
- Acceptance Gate Ledger/evidence
- Integration rerun
- deterministic CompletionSummary

## 5. Model Layer

`app/llm/factory.py`의 current implementation은 DeepSeek adapter 하나다. ModelRouter는 role/model tier에 따라 Flash/Pro/Vision을 고른다.

OpenRouter, OpenAI-compatible internal endpoint, vLLM/SGLang 등은 **현재 구현이 아니라 future provider work**다.

## 6. Tool / Execution Layer

주요 tool:

`read_file`, `list_dir`, `grep`, `find_symbol`, `write_file`, `edit_file`, `bash`, `build_frontend`, `browser_check`, `ask_user`, `update_tasks`, `update_gates`, `save_skill`, `read_tool_result`.

- path는 workspace 경계 안으로 resolve한다.
- mutation은 approval policy를 거친다.
- bash 기본은 Docker sandbox; host mode는 opt-in.
- dangerous/self-kill command(`rm -rf`, sudo, kill/pkill, uvicorn 등)는 차단한다.
- Acceptance verification도 `DockerSandbox.run_verify()`를 사용한다.
- `build_frontend`는 배포 dist 갱신 때문에 host npm build를 명시적으로 사용한다.

ExecutionBackend 공통 interface(Local/Docker/SSH)는 아직 정리되지 않았다.

## 7. Persistence

PostgreSQL tables:

- sessions / messages / tasks / acceptance_gates
- checkpoints (legacy/deprecated — writer/reader 없음, FK 정리 호환용으로 테이블만 유지. rollback·durable resume 미제공)
- agent_runs
- push_devices
- scheduled_jobs
- refinements

Sessions에는 running/final_status, auto_approve, model_tier, logical budget, compaction summary/covered 등이 있다.

## 8. Context / Memory / Skills

- 131k logical budget, 75% compaction, 95% block
- compaction summary DB persistence
- symbol-aware file reading
- recoverable tool-result pruning
- selective Skills
- evidence-bound ROOM_MEMORY with provenance guard

Skills와 Memory는 다르다: Memory는 검증된 프로젝트 사실, Skill은 재사용 가능한 해결 절차다.

## 9. Automation

`scheduled_jobs.next_run_at`(UTC)이 authority다. Scheduler는 20초 polling으로 due jobs를 찾고 atomic claim/overlap skip/retry를 적용한다. 현재 recurrence는 one-shot, daily, interval이다. Deferred/Condition watcher는 아직 구현되지 않았다.

## 10. MCP

stdio JSON-RPC MCP server가 high-level capability만 노출한다.

- `forge_execute`
- `forge_status`
- `forge_result`
- `forge_cancel`

`task_id == session_id`라 DB 결과와 global Auto Resume를 재사용한다. MCP transport 자체는 stdio/local이고 remote MCP auth/resources는 미구현이다.

## 11. Mac Remote

- Terminal: host PTY + WebSocket/xterm
- Screen: `screencapture` 기반 단일 JPEG polling, 약 150ms 후 다음 frame 요청
- Remote input: pointer/mouse/keyboard → HTTP `POST /api/mac/input`; mouse move는 ~25Hz throttle
- coordinate mapping: contain letterbox + portrait rotation 보정
- Camera: imagesnap polling PoC

이것은 현재 WebRTC 기반 원격 데스크톱이 아니다.

## 12. Evaluation / RSI

- R0: 25 deterministic fixture tasks
- checker self-test로 false-positive/정답 노출 방지
- R1: candidate worktree에서 `forge:<goal>` self-modification 가능
- no-op candidate는 benchmark 전에 REJECT
- promotion gate: success rate → cost per success → elapsed
- 자동 main merge는 하지 않고 사람 승인 유지

## 13. Deliberately Not Yet

- provider-independent OpenAI-compatible endpoint
- independent durable worker/queue process
- Deferred/Condition Jobs
- generic Local/Docker/SSH ExecutionBackend
- bounded parallel fresh workers
- full browser/computer-use automation
- WebRTC screen streaming
