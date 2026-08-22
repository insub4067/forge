# FORGE 트러블슈팅 기록

> 실제 운영에서 겪은 문제와 해결. 기준: 2026-08-22 `main`.

## LLM / DeepSeek

### 400 — tool_calls 뒤 tool message 누락

원인: 도구 결과가 다음 LLM request에 포함되지 않음.  
해결: 매 호출을 `[system_msg, *projected/all_messages]` 구조로 통일해 tool call/result pairing 보존.

### 400 — reasoning_content 계약 오류

thinking role의 긴 tool loop에서 `reasoning_content` 재전송 계약 때문에 400이 날 수 있었다.

현재 recovery:

1. reasoning 관련 오류 분류
2. reasoning_content 제거
3. thinking off
4. 재시도
5. 해당 session은 이후 호출에서도 strip 정책 기억

단발 테스트보다 실제 실패 세션 로그를 우선 확인한다.

### 429 / 5xx / timeout / connection

transient 오류는 1/2/4초 backoff로 최대 3회 재시도한다. 이미 stream delta가 사용자에게 전달된 뒤 실패한 요청은 중복 생성 위험 때문에 자동 retry하지 않는다.

## Context / 비용

### Planner가 전체 토큰의 67%를 소비

원인: Planner를 항상 Pro + thinking high로 사용하고 탐색 범위가 넓었음.

해결:

- Planner Flash + medium 기본
- Triage가 COMPLEX일 때만 Pro + high
- 최소 탐색 지침
- tool result pruning
- read-only 병렬 prefetch

### Compaction 후 바로 context_blocked

과거 로직은 `prompt + completion`을 pressure로 보고, compaction 성공 후에도 압축 전 usage로 95% block을 검사했다.

현재는 provider 실측 `prompt_tokens`만 사용하고, compaction 성공 시 다음 model call에서 줄어든 context를 재측정한다.

### cache token 의미 오류

과거 `hit + miss`를 `cached_tokens`라고 표시했는데 이는 사실상 전체 prompt였다.

현재는 `cache_hit_tokens`, `cache_miss_tokens`, `cache_hit_ratio`를 분리한다.

## Run / 세션 지속성

### 앱을 닫으면 진행이 사라져 보임

사용자 메시지는 run 시작 즉시 DB에 저장한다. 브라우저 SSE가 끊겨도 서버 run은 계속될 수 있고 PWA는 `/sessions/{id}/status`를 polling해 `running`, `role`, `activity`, `waiting_for`를 표시한다.

### 동일 세션에 요청을 다시 보내면 run이 겹침

현재 `try_begin`으로 run을 원자적으로 선점한다. 이미 실행 중이면 새 AgentRuntime을 겹쳐 띄우지 않고 기존 run에 메시지를 injection한다.

### 서버 재시작 후 running=true가 남음

startup `reconcile_interrupted_runs()`가 중단된 run을 감지해 복구 안내 메시지를 남기고 flag를 정리한다.

주의: 이것은 실제 execution stack resume이 아니다. durable worker/resume은 아직 미구현.

### run exception이 나면 응답이 조용히 사라짐

현재 run crash 시 오류 assistant message를 history에 저장한다.

## 승인 / 질문

### 앱을 떠난 동안 approval/question에서 영원히 대기

approval/question future는 600초 timeout을 가진다. cancel도 pending future를 해제해 run이 매달리지 않게 한다.

재접속 시 `/status`의 `waiting_for`로 현재 대기 상태를 확인한다.

## Workspace / 파일 브라우저

### 새 방이 홈 디렉터리를 workspace로 잡아 Git/Skill이 안 보임

신규 session은 workspace 선택을 필수화했다.

### 파일 브라우저로 workspace 밖 파일 조회 가능

`/fs/list`, `/fs/read`는 `session_id`의 workspace boundary를 확인한다. 경계 밖 path는 차단한다.

## Git / Kanban

### git status 파일 경로 첫 글자 손실

과거 `_git` 출력 전체 `.strip()` 때문에 status 정렬이 밀린 케이스가 있었다. status parsing 시 prefix 공백을 고려한다.

### 실행 중 Kanban이 0개로 보임

Kanban open 시 task를 다시 읽고 running polling 중에도 task를 갱신한다. task status 변화는 채팅에도 인라인 표시한다.

## 모바일 / PWA

### Service Worker 업데이트 무한 reload

증상: 폰·브라우저가 blank → skeleton → 내용 → blank를 계속 반복. Safari에선 상단 로딩바가 끊임없이 뜬다. 서로 다른 세션방을 오가는 것처럼 보이지만, 실제로는 매 reload가 landing 상태를 다시 그리는 착시다.

원인: `registerType: 'autoUpdate'`는 새 SW가 감지될 때마다 페이지를 **자동 reload**한다. 개발 중 dist를 짧은 간격으로 여러 번 rebuild하면 그때마다 새 precache manifest(=새 SW)가 생겨 reload가 연쇄된다. 배포 dist를 서빙하는 Cloudflare 터널 경유 접속도 동일하게 당한다.

해결: `registerType: 'prompt'`로 전환해 SW가 페이지를 자동 reload하지 않게 하고, 적용 시점을 `main.js`가 통제한다. 자동 적용은 **브라우저 세션당 최대 1회**(`sessionStorage['forge_reloaded']`)만 허용하고, 이후 새 버전은 toast로만 안내한다. 구조적으로 루프가 불가능하다.

교훈: 사용자가 라이브로 지켜보는 동안엔 rebuild 빈도를 줄이고, 변경을 모아 한 번에 build한다. `prompt` 모드에선 새 버전이 새로고침 전까지 적용되지 않으므로, 반영 확인은 "당겨서 새로고침" 후에 한다.

### 서버는 일하는데 화면은 멈춘 것처럼 보임

SSE `busy`만 보던 UI를 `sessionRunning`까지 확장했다. `/status.activity`를 배너/typing indicator에 표시해 `bash · ...`, `추론 중`, `작성 중` 같은 현재 활동을 보여준다.

### history 열 때 welcome 화면이 깜빡임

기존 세션은 message loading 동안 skeleton을 표시하고 새 session만 welcome placeholder를 바로 보여준다.

### iOS safe-area

홈화면 PWA를 기준으로 header/footer/drawer/overlay safe-area를 적용한다. Safari browser와 standalone의 inset 값은 다를 수 있다.

### Cloudflare Access 뒤에서 PWA가 구버전에 영구 고착 (가장 함정)

증상: 서버(dist)는 최신인데 폰 PWA는 며칠이 지나도 옛 버전 그대로. autoUpdate/prompt 어느 쪽으로 바꿔도, 캐시 헤더를 손봐도 안 바뀜.

진단: 공개 URL로 `curl -sI https://<host>/sw.js` → **302 redirect to `<team>.cloudflareaccess.com/.../login`**. `/`, `/index.html`, `/assets/*`까지 전부 302. 즉 사이트 전체가 Access로 보호돼, **서비스워커의 `/sw.js` 업데이트 요청이 세션 만료 시 로그인 HTML로 리다이렉트**되어 SW가 영원히 갱신되지 않는다. 캐시가 아니라 인증이 원인.

해결: Zero Trust → Access → Applications에서 **정적 PWA 경로를 Bypass**로 추가.
- 최소: `sw.js` 하나만 Bypass(Everyone)해도 SW 업데이트가 뚫린다.
- 권장: `sw.js`, `index.html`, `assets/*`, `manifest.webmanifest`, `workbox-*.js`, `push-handler.js`까지 Bypass. 데이터는 `api/*`만 Access로 보호하면 안전(정적 셸엔 비밀정보 없음).

부수 조치(origin): backend에서 `sw.js`·`index.html`을 `Cache-Control: no-store`로 서빙해 엣지/브라우저 캐시 고착도 방지(main.py `_NO_STORE`).

## 웹 푸시

### 등록 기기는 있는데 sent:0 (발송 실패)

증상: `/push/test`가 `{"sent":0,"total":1}`. `send_one`이 예외를 삼켜 조용히 실패.

원인: pywebpush `vapid_private_key`에 **PEM 파일 내용(string)**을 넘김. pywebpush는 문자열을 raw base64url 키로 해석하려다 `ValueError: Could not deserialize key data`로 실패한다.

해결: PEM **파일 경로**를 넘겨 `Vapid.from_file`이 파싱하게 한다(`push._private_key()`가 경로 반환). 예약 작업 완료 알림도 같은 경로(`_notify_done`)를 쓰므로 함께 복구된다.

## 예약 작업 / 맥 탭

### 예약 생성 모달이 사이드바 뒤에 깔림

`.modal-overlay` z-index(100)가 드로어 `.rooms-overlay`(150)보다 낮았다. 예약 모달에 `.job-modal`(z-index 200)을 부여해 사이드바 위로 띄운다.

### 모달 입력이 오른쪽으로 넘침

`.modal-field`에 `box-sizing: border-box`가 없어 `width:100% + padding`이 모달을 28px 넘쳤다. datetime-local/time 입력에서 특히 두드러진다. `box-sizing: border-box; max-width:100%`로 해결.

### 스와이프 삭제 시 삭제 버튼이 행 내용과 겹쳐 보임

`.job-item`에 불투명 배경(`var(--panel)`)과 `position:relative`, `.job-item.swiped { transform: translateX(-84px) }`가 없으면 뒤의 삭제 버튼이 비쳐 겹쳐 보인다(`.room-swipe` 패턴 재사용). 배경이 투명하면 발생.

### 화면 보기 강제 landscape (iOS)

iOS Safari/PWA는 `screen.orientation.lock()`을 지원하지 않는다. 세로에서 강제 가로로 보이려면 CSS 회전을 쓴다:
`.mac-overlay.is-screen { inset:auto; top:0; left:100%; width:100vh; height:100vw; transform-origin:top left; transform:rotate(90deg); }` (`@media (orientation: portrait)`에서만). `top:50% + translate(-50%,-50%) + rotate`는 회전 후 위치가 어긋나므로 `left:100% + transform-origin:top left` 패턴을 쓴다. 지원 브라우저(안드로이드)는 `screen.orientation.lock('landscape')`도 시도(try/catch).

### 전체화면 오버레이가 드로어와 겹쳐 보임

`fade-in` 애니메이션 **중간 프레임**을 캡처하면 반투명 상태로 드로어가 비친다. 애니메이션(0.16s) 종료 후엔 불투명. 실제 버그가 아니므로 재캡처로 확인한다.

### 예약으로 자동 생성된 세션 식별

`store.list_rooms()`가 `ScheduledJob.session_id` 집합과 대조해 `scheduled: true`를 부여하고, 프런트가 "예약" 뱃지를 표시한다. 스키마 변경 없이 조인으로 계산.

### 맥 절전 방지(caffeinate) 재시작 내성

`caffeinate` 자식 프로세스는 백엔드 재시작 시 고아가 되어 in-memory 핸들로는 못 끈다. `pgrep -f "caffeinate -dimsu"` / `pkill -f`로 상태 판정·종료해 재시작 후에도 토글이 동작하게 한다.

## 로그 / 관측

- Agent의 `send()` 이벤트는 JSONL event/action log에 기록
- `GET /api/metrics/summary` — 전체 효율
- `GET /api/rooms/{id}/metrics` — session 효율
- `/status` — live run 상태

JSONL 로그는 현재 감사/장애 추적용이다. 재시작 후 실행을 이어가는 authoritative event replay 계층은 아니다.

## 배포

- frontend: `npm --prefix frontend run build`
- backend 변경: uvicorn 재시작 필요
- backend 재시작은 진행 중 run을 중단시키므로 배포 전 running session을 확인하는 것이 안전하다.

## 병렬 개발 주의

여러 코딩 agent가 같은 branch/file을 동시에 수정하면 충돌·중복 선언이 발생할 수 있다. 실제로 병합 후 Vue 함수/상수가 중복 선언되어 build가 깨진 사례가 있었다.

원칙:

1. 작업 전 최신 main 확인
2. 동일 파일 병렬 수정 최소화
3. 병합 후 frontend build + runtime tests 실행
4. commit/push 전 최신 diff 재검토
