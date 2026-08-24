# FORGE Troubleshooting

> 현재 source 기준 운영 노트. 과거 incident narrative보다 이 절차를 우선한다.

## Backend 변경이 반영되지 않음

`backend/app/**` Python 코드를 바꾸면 현재 실행 중인 process를 재시작해야 한다. FORGE Agent 자신은 `pkill/kill/uvicorn`이 BLOCKED_COMMANDS라 backend를 재시작할 수 없다. 필요하면 최종 보고에 재시작 필요를 남기고 사람이/supervisor가 수행한다.

반대로 `docs/agents/*.md` role prompt는 `_load_role()`이 매 role call마다 읽으므로 **프롬프트만 바꿨다면 재시작 불필요**다.

## Frontend 수정이 화면에 안 보임

소스(`frontend/src/**`)만 고치고 `dist`를 갱신하지 않은 경우가 많다.

```bash
cd frontend
npm run build
```

Agent에서는 `build_frontend` tool을 사용한다. `frontend/dist`를 직접 패치하지 않는다.

`sw.js`, `index.html`은 server가 no-store로 제공한다. 그래도 PWA가 stale하면 browser/PWA service worker 상태를 확인한다.

## Backend tests

FORGE repo 표준:

```bash
cd backend
./.venv/bin/python -m pytest -q
```

`.venv`가 없거나 `psycopg`가 빠진 system python으로 돌리면 환경 오류를 코드 실패로 오해할 수 있다.

## Context가 갑자기 100% 이상 / 매 턴 비쌈

logical budget은 131072. ~75%에서 compaction한다. compaction summary/covered는 PostgreSQL에 저장돼 다음 run에서 복원된다.

확인:

- 해당 session의 compact summary가 DB에 저장됐는지
- history가 summary의 `covered`보다 짧아져 복원이 거부된 것은 아닌지
- 큰 tool 결과가 `read_tool_result` 없이 계속 context에 들어오는지

작업 경계라면 `새 세션 + 같은 workspace`가 가장 안전한 reset이다.

## Gate가 맞는 코드를 실패시킴

Acceptance gate failure와 generic test failure를 구분한다.

1. gate `verification_method`와 `expected_result` 확인
2. command가 실제 observable behavior를 검증하는지 확인
3. `grep -q`/심볼 존재/generic pytest 재탕이면 gate 품질 문제
4. cwd는 이미 workspace임 — 불필요한 `cd`로 존재하지 않는 path에 들어가지 않는지 확인
5. process evidence의 exit/output tail 확인

잘못된 gate 때문에 맞는 코드가 `verification_failed`가 되는 false-negative는 관찰 대상이다. gate를 억지 PASS시키지 말고 gate 작성 규칙을 좁게 고친다.

## Gate가 0개

Developer가 정상적으로는 구현 전에 gate를 만든다. 코드가 변경됐는데 gate가 없으면 Gate Recovery가 딱 1회 실행된다. 그래도 없으면 `completed_unverified`이며 auto push하지 않는다.

`gate_coverage` event의 `gated / recovered_gated / generic_only`를 확인한다.

## `completed_unverified`인데 push가 안 됨

의도된 정책이다. fully verified가 아니므로 local commit은 가능하지만 origin push는 막는다.

## 최종 보고가 새로고침 후 사라짐

현재는 process-owned CompletionSummary를 history에 저장한다. 최신 source인데 사라진다면 messages persistence/API load 문제로 취급한다. 모델의 직전 자연어 메시지를 authoritative final report로 대체하지 않는다.

## 모델 칩과 실제 모델이 다름

model tier는 세션별 DB 값이 authority다. 방 전환 시 `/api/rooms`의 `model_tier`로 UI를 복원하고 선택 즉시 `/api/sessions/{id}/model-tier`에 저장한다. localStorage는 신규 세션 기본값일 뿐이다.

## auto-approve가 다른 방으로 새어 감

현재 auto-approve도 세션별 DB 값이 authority다. 방 선택은 서버 값을 UI로 읽어야 하며 navigation 자체가 다른 session의 권한을 쓰면 regression이다.

## Project Memory가 이상한 사실을 말함

현재 source가 항상 우선이다. `ROOM_MEMORY.md`는 보조 정보다.

새 memory는 `{fact, source, evidence}` candidate로 생성되고 `memory_guard` validation을 통과해야 한다. `project_memory_rejected` event에서 `no_source / invalid_source / unsupported_claim / duplicate / no_evidence` 등의 이유를 확인한다.

기존 memory가 source와 충돌하면 memory를 고치고 해당 false-memory 사례를 regression fixture로 추가한다.

## 서버 재시작 후 run

`AUTO_RESUME=1`이면 startup에서 `running`으로 남은 session을 찾고 workspace가 유효하면 history 기반으로 headless resume한다.

자동 재개하지 않는 대표 조건:

- `final_status == resuming` (재개 중 또 crash → loop guard)
- workspace 없음/`/`/실제 디렉터리 아님

이 resume는 process checkpoint continuation이 아니라 새 AgentRuntime loop 재구성이다.

## DB/schema 문제가 조용함

현재 `main.py` lifespan은 create/migration/resume setup을 broad `except Exception: pass`로 감싼다. startup은 떠 있는데 table/column이 안 맞는 이상 증상이면 DB migration 실패를 의심하고 PostgreSQL schema/error log를 직접 확인한다. 이 broad exception은 개선 대상이다.

## Mac Screen은 보이는데 입력이 안 됨

현재 remote input 경로는 WebSocket이 아니라 `POST /api/mac/input`이다.

확인:

- UI 원격제어 toggle이 켜졌는지
- Mac Accessibility/Input 권한
- `cliclick` 설치/호출 가능 여부
- pointer 좌표가 `containContentRect`/`toScreenXY`로 letterbox/rotation 보정되는지
- iOS에서 `click`이 아니라 `pointerdown` handler가 붙는지

mouse move는 ~25Hz throttle이 정상이다.

## Mac Screen frame이 끊김

현재 WebRTC가 아니라 screenshot JPEG polling이다. 이미지 load 후 약 150ms 뒤 다음 frame을 요청한다. 실시간 원격데스크톱 FPS를 기대하면 architecture 한계다. WebRTC proposal은 아직 구현이 아니다.

## Terminal

Terminal은 **host PTY**다. WebSocket 연결로 xterm과 stdin/stdout을 주고받는다. Agent Docker bash와 같은 sandbox terminal이라고 가정하지 않는다. 원격 shell 권한이므로 auth/network boundary를 강하게 유지한다.

## MCP task와 서버 재시작

`task_id == session_id`. DB history는 남고 Auto Resume가 유효하면 session을 이어갈 수 있다. 다만 stdio connection 자체는 끊기므로 MCP client는 재연결해야 한다.

## Agent가 수정했는데 auto commit에 빠진 파일

Auto commit은 안전을 위해 `write_file/edit_file`로 기록된 path만 stage/commit한다. bash/sed 등으로 바꾼 파일은 사람의 기존 변경을 잘못 커밋하는 것보다 놓치는 쪽을 택해 자동 commit 대상에서 빠질 수 있다. 필요하면 git status/diff로 확인한다.
