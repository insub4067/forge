# FORGE — 기능 목록

> 기준: 2026-08-23 `main`

## Agent Runtime

| 기능 | 상태 |
|---|---|
| Triage CHAT / AGENT + SIMPLE / COMPLEX | ✅ |
| 올인원 Developer(설계+구현+검증+수정) | ✅ |
| Developer flash+think-medium 기본 | ✅ |
| 실패 시 pro+think-high 1회 승격(Jr→Sr) | ✅ |
| Triage → Chat/Developer 라우팅 | ✅ |
| 최대 step / review cycle 제한 | ✅ |
| 동일 tool 반복 감지 | ✅ |
| 동일 session 동시 run 가드 | ✅ |
| 실행 중 메시지 injection / cancel | ✅ |

## Context / 비용 효율

| 기능 | 상태 |
|---|---|
| provider 실측 prompt token 기반 pressure | ✅ |
| Tool result model-free pruning | ✅ |
| 75% 비파괴 context compaction / 95% hard block | ✅ |
| stable prefix + DeepSeek cache telemetry | ✅ |
| selective Skill retrieval | ✅ |
| read-only tool 병렬 prefetch | ✅ |
| role/session 비용·성공률 metrics | ✅ |
| Planner/Reviewer/Debugger 제거(올인원) | ✅ |
| reasoning 400 session 반복 retry 제거 | ✅ |
| Tool Script/RPC Mode | ⬜ |

## Tool / Execution

| Tool | 상태 | 비고 |
|---|---|---|
| read_file / list_dir / grep | ✅ | read-only |
| write_file / edit_file / bash | ✅ | 승인 |
| ask_user / update_tasks | ✅ | runtime |
| save_skill | ✅ | 승인 |
| build_frontend | ✅ | host npm production build |

- Docker Sandbox 기본 + `SANDBOX_MODE=host` 옵트인 ✅
- mutation 전 git SHA checkpoint / unified diff ✅
- FORGE 프론트 소스 수정 후 Agent가 host build까지 자율 검증 가능 ✅

## Session / Persistence

- PostgreSQL 세션·메시지·task·checkpoint 영속화 ✅
- agent_runs token/cache/model/tool/retry/compaction/elapsed 계측 ✅
- interrupted run reconcile / crash history ✅
- JSONL durable event/action log ✅
- 서버 재시작 후 실제 실행 resume ⬜
- authoritative event replay ⬜

## Remote / PWA

- 세션 / 예약 / 맥 중심 모바일 PWA 구조 ✅
- 승인·질문 UI + 재접속 후 pending 승인 복구 ✅
- `/status` polling / SSE 단절 복구 ✅
- Kanban / Git / Files / Skills / Metrics ✅
- 다중 이미지 + Vision / gallery ✅
- PWA foreground Service Worker update 확인 + stale cache 방지 ✅
- **Mac 화면 보기(view-only)** ✅
- **Mac host PTY Terminal(WebSocket + xterm.js)** ✅
- **Mac Camera(imagesnap JPEG polling PoC)** ✅
- 모바일 Terminal 보조키 / resize ✅
- Web Push ⬜

> Terminal은 현재 Docker-only proposal과 달리 **개인 Mac host PTY**로 먼저 구현됐다. 사실상 원격 shell이므로 인증/네트워크 접근통제 검증을 최우선 보안 항목으로 본다.

> Camera는 WebRTC가 아니라 `imagesnap` 단일 프레임 polling PoC다. 장기 streaming 구조는 별도 검토한다.

## Persistent Automation

- 예약 작업 UI/기반 구현 진행 중 🟡
- workspace 미지정 예약 작업 전용 `~/forge-jobs` 처리 ✅
- Scheduled / Condition Job 완성도 검증 🟡
- Web Push ⬜
- durable worker 기반 재시작 후 정확한 continuation ⬜

## Security / Guard

- mutation approval / Docker Sandbox / workspace file boundary ✅
- Cloudflare Tunnel과 Access authorization을 별도 계층으로 문서화 ✅
- Host Terminal WebSocket authorization boundary 재검증 필요 ⚠️
- Camera/Screen stream authorization 및 privacy boundary 지속 검증 필요 ⚠️

## 다음 우선순위

1. Host Terminal / Screen / Camera 인증·권한 경계 보안 검증
2. durable worker + 실제 resume/event replay
3. Scheduled / Condition Jobs + Web Push 완성
4. Tool Script/RPC Mode
5. ExecutionBackend(Local/SSH/Docker)
6. bounded RSI evaluation pipeline(candidate → benchmark → promotion/rollback)

Multi-Agent, MCP, Vector Search는 실제 병목/요구가 확인된 뒤 도입한다.
