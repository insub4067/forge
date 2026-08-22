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

원인: reload guard가 module 변수라 reload마다 초기화되어 `controllerchange → reload` 루프가 반복됨.

해결: `sessionStorage` 기반 탭 세션당 1회 reload guard.

### 서버는 일하는데 화면은 멈춘 것처럼 보임

SSE `busy`만 보던 UI를 `sessionRunning`까지 확장했다. `/status.activity`를 배너/typing indicator에 표시해 `bash · ...`, `추론 중`, `작성 중` 같은 현재 활동을 보여준다.

### history 열 때 welcome 화면이 깜빡임

기존 세션은 message loading 동안 skeleton을 표시하고 새 session만 welcome placeholder를 바로 보여준다.

### iOS safe-area

홈화면 PWA를 기준으로 header/footer/drawer/overlay safe-area를 적용한다. Safari browser와 standalone의 inset 값은 다를 수 있다.

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
