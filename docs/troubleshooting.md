# FORGE 트러블슈팅 기록

실제 운영에서 겪은 문제와 해결. 같은 증상 재발 시 참고.

## LLM / DeepSeek

### DeepSeek 400 — "tool_calls must be followed by tool messages"
- **증상**: 도구 호출 다음 스텝마다 400. 모든 role에서 발생.
- **원인**: 도구 결과를 `all_messages`에만 append하고 LLM에는 별도 `messages`를 보내, tool 응답이 빠진 채 전송.
- **해결**: 매 호출 `[system_msg, *all_messages]`로 통일(`agent.py`). 도구 결과가 항상 포함됨.

### DeepSeek 400 — "reasoning_content in the thinking mode must be passed back"
- **증상**: thinking 모드 긴 tool-loop에서 스텝 하나가 400 → run이 계획 단계에서 멈춤/응답 유실.
- **1차 시도**: reasoning_content를 벗겨 재시도 → 재시도도 같은 400(불충분).
- **해결**: reasoning 400 시 **thinking을 꺼서 재시도**(`_stream_with_recovery`). non-thinking 호출은 reasoning_content 계약이 없어 확실히 회피. 세션별로 학습(`_strip_reasoning_sessions`).
- **주의**: 통제 실험(단발 호출)으로는 재현이 안 됨 — 실제 실패 세션/에러로그로 확인.

### 일시적 API 오류(429/5xx/timeout)
- `_classify_error`로 reasoning/transient/terminal 분류. transient는 1·2·4초 백오프로 최대 3회 재시도.

### 응답이 짧다 / "추론은 하는데 말이 없다"
- thinking 모드 role(planner 등)은 reasoning이 길고 최종 content가 짧을 수 있음. 대화형 질문이 planner로 triage되면 답변 대신 계획/탐색만 함.

## 대화 유실

### 앱 껐다 켜면 대화가 끊겨 있음
- **원인**: 히스토리를 run 완료 시에만 저장 → run 크래시(위 400 등)나 앱 종료 시 그 턴이 통째로 유실.
- **해결**:
  1. 사용자 메시지를 **수신 즉시 저장**(`/chat` 엔드포인트).
  2. run 크래시 시 **"작업 중 오류" 어시스턴트 메시지를 저장**해 조용히 사라지지 않게(`run_and_close`).
  3. 앱은 닫혀도 서버 run은 계속 → 재접속 시 실행 여부 표시 + 완료 자동 갱신.

### 메시지 0인데 컨텍스트 가득(유령)
- 과거 크래시로 대화는 유실됐는데 `used_tokens`만 남음.
- **해결**: 메시지 로드 시 히스토리가 비면 `used_tokens`를 0으로 자가 치유(`get_messages`).

## Git 화면

### 파일 경로 앞 글자 잘림("ackend/...")
- **원인**: `_git`이 출력 전체에 `.strip()`을 걸어 status 첫 줄의 앞 공백을 먹음 → `slice(3)` 정렬이 밀림.
- **해결**: 프론트 `parseStatus`에서 구분 공백이 없으면 복원.

### git API 중복 정의
- 병렬 작업으로 log/file-diff/commit이 두 번씩 정의 → 견고한 버전만 남김.

## 비용

### planner가 토큰의 67% 소비
- pro+thinking high로 과탐색.
- **해결**: planner를 flash 기본으로, triage가 COMPLEX 판정할 때만 pro 승격. + 도구 결과 pruning(20k→~4k) + 최소 탐색 지침.

## 모바일 / PWA

### safe-area 브라우저 vs PWA 차이
- iOS가 두 컨텍스트에서 다르게 보고(브라우저 0, standalone은 노치 inset). 각 환경에선 정상. 타깃은 홈화면 PWA.

### 리소스 업데이트가 앱 껐다 켜야 반영
- **해결**: SW `controllerchange` → 자동 리로드(작업 중이면 유휴 때까지 미룸) + 포그라운드 복귀 시 `update()`.

### 홈화면 이름이 "에이전트"로 남음
- manifest name·`<title>`·`apple-mobile-web-app-title` 모두 FORGE로. iOS가 이름을 캐시하면 홈화면 아이콘 삭제 후 재추가.

## 배포
- 이 Mac이 production(cloudflared 터널 → agent.smarttradecorp.com → localhost:8790).
- 프론트: `npm --prefix frontend run build`로 dist 갱신 → 즉시 반영.
- 백엔드: uvicorn 재시작.

## 협업 주의
- 병렬 세션(다른 Claude Code 창)이 같은 파일을 동시 편집하면 서로 덮어씀. push 전 `git fetch` + rebase.
