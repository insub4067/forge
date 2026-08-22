# FORGE — 작업 진행 상태

> 마지막 갱신: 2026-08-23 `main`

## 현재 요약

- Phase 1 — Agent Core: 완료
- Phase 2 — Code Modification: 완료
- Phase 3 — Remote Operation: 진행 중이나 Terminal/Screen/Camera까지 실제 구현
- 최적화 기준: **cost per successfully completed task**

## 최근 핵심 변화

- [x] SIMPLE 작업 Planner 제거: `Triage → Coder → Reviewer`
- [x] COMPLEX만 Planner 실행
- [x] reasoning_content 400을 겪은 session의 후속 thinking을 미리 꺼 반복 retry 낭비 제거
- [x] `build_frontend`: Agent가 FORGE 프론트 수정 후 host production build까지 직접 수행
- [x] Mac host PTY + WebSocket + xterm.js Terminal
- [x] Mac 화면 보기(view-only)
- [x] Mac Camera `imagesnap` JPEG polling PoC
- [x] PWA 재접속 시 pending approval 복구
- [x] PWA foreground update 확인 및 stale Service Worker 완화

## Agent Runtime

현재 핵심 경로:

```text
CHAT    → Chat
SIMPLE  → Coder → Reviewer → 필요 시 Debugger ↔ Reviewer
COMPLEX → Planner → Coder → Reviewer → 필요 시 Debugger ↔ Reviewer
```

Reviewer task authority, review limit, repeated tool guard, concurrent-run guard, runtime message injection, cancel은 유지한다.

## Tool / Self-development

기존 read/write/edit/bash/grep/list/ask_user/update_tasks/save_skill에 `build_frontend`가 추가됐다.

FORGE가 자기 repository를 workspace로 작업할 때 프론트 소스 수정 → host `npm run build` → 결과 확인까지 Agent가 닫을 수 있다. 이는 bounded self-improvement에 필요한 실행 능력의 일부지만, 자동 benchmark/promotion/rollback까지 닫힌 RSI는 아직 아니다.

## Remote Mac

### Screen

- view-only Mac 화면 확인 구현
- 장기적으로 선택 Window/Simulator 및 저지연 streaming 고도화 검토

### Terminal

- host PTY
- `/api/terminals/ws`
- xterm.js
- session workspace에서 interactive shell
- 모바일 Tab/Esc/Ctrl-C/Ctrl-D/방향키

**중요:** 현재 구현은 Docker-only terminal이 아니라 host shell이다. WebSocket 인증/authorization과 네트워크 경계를 최우선으로 재검증해야 한다.

### Camera

- `imagesnap`으로 JPEG 단일 frame capture
- 약 400ms polling 방식의 Live View PoC
- 카메라 권한/미설치 오류 처리

현재는 WebRTC 지속 stream이 아니며, frame마다 capture process를 띄우므로 제품화 전 성능/자원/보안 검토가 필요하다.

## Persistent Automation

예약 기능 기반과 workspace fallback(`~/forge-jobs`)이 들어왔지만 다음을 완료 조건으로 본다.

- Scheduled / Deferred / Condition Job semantics 검증
- restart 이후 durable continuation
- 중복 실행 방지/idempotency
- timezone/DST
- Web Push
- 실행 이력/실패 재시도 정책

## Persistence / Telemetry

PostgreSQL session/message/task/checkpoint/agent_runs, JSONL event log, `/status`, interrupted-run reconcile은 구현돼 있다.

**진짜 durable resume은 아직 아니다.** 서버 재시작 후 실행 stack/step을 복원하는 worker + authoritative replay가 필요하다.

## 보안 최우선 점검

1. `/api/terminals/ws` 인증·session ownership·workspace authorization
2. Screen/Camera endpoint 인증 및 public exposure 차단
3. `build_frontend`가 의도된 workspace/command만 실행하는지 경계 검증
4. Host mode와 Agent approval 정책의 trust boundary 명확화
5. Zero Trust/VPN을 전제로 하되 application authorization도 독립적으로 유지

## 다음 핵심 작업

### P0 — Remote Host Security

- [ ] Terminal WebSocket 인증/ownership 검증
- [ ] Screen/Camera endpoint 권한 검증
- [ ] remote host capability audit

### P1 — Durable Worker / 실제 Resume

- [ ] FastAPI lifecycle에서 Agent worker 분리
- [ ] durable queue
- [ ] authoritative event stream/replay
- [ ] 서버 재시작 후 run continuation

### P2 — Persistent Automation 완성

- [ ] Scheduled/Deferred/Condition Job 안정화
- [ ] Web Push
- [ ] restart/idempotency/timezone 검증

### P3 — Tool 효율

- [ ] Tool Script/RPC Mode

### P4 — Bounded RSI

- [ ] 개선 후보 branch/worktree 생성
- [ ] 고정 benchmark
- [ ] success rate guardrail
- [ ] cost/time/human intervention 비교
- [ ] 개선 시 promotion, 악화 시 rollback

## 검증 원칙

새 기능 개수보다 다음 순서를 우선한다.

```text
성공률 유지/향상
→ cost per successful task 감소
→ elapsed time 감소
→ human intervention 감소
```

FORGE는 스스로 코드를 수정할 수 있는 단계에 도달했지만, **측정 → 후보 생성 → 격리 검증 → 선택 → 반복**이 자동으로 닫히기 전에는 완전한 RSI라고 부르지 않는다.
