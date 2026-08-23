# 세션 인수인계 — 모바일 UX 정리 + 신뢰성 사각 메우기 (2026-08-24)

> 이 세션은 사용자가 폰으로 FORGE를 쓰며 발견한 문제를, 옆에서 Claude Code가 로그로
> 재현·수정하는 리뷰 루프로 진행됐다. 대부분 "모델이 멍청"이 아니라 "하네스 경계 구멍"이었다.

## 0. TL;DR — 다음에 할 일

미구현 proposal 중 **안전·가치 큰 것부터**. 아래는 이유상 지금 안 한 것:
- `scheduled-condition-jobs` Condition 엔진 — 스케줄러 대공사 + 방향 미확정. 설계 확정 후.
- 런타임 스모크 2단계(상호작용 검증) — showHidden류(try/catch로 삼킨 것)를 잡으려면 필요.
  단 셀렉터 의존이라 verify 불안정 위험. 신중히.
- `low-cost-model-routing`·`web-search-tools` — **벤치 없이 금지**(제안서 원칙). 벤치 먼저.
- RSI candidate worktree — 자기수정. evidence 없는 자기수정 금지.
- `tauri-desktop-host`·`forge-mcp-agent-runtime`·Computer Use·WebRTC — 대형/보류.

## 1. 이번 세션에 한 것 (전부 push)

**신뢰성 사각**
- **컨텍스트 초과 근본**: `.env`의 `LOGICAL_BUDGET=262144`가 config default(131072)를 덮어써
  compact 임계가 196K가 됨 → 128K 모델 한도 전에 compaction이 절대 안 돎. `.env` 131072로 수정.
  (`96d59a8`)
- **compaction이 안 돌던 버그**: `_safe_split`이 "tool_calls 없는 assistant"만 경계로 허용 →
  user 1개 + tool 연속인 developer run에서 경계 못 찾아 0 반환. tool만 금지로 완화. (`24f1a86`)
- **선제 compaction**: in-memory 요약이 재시작 시 유실 → 긴 세션 첫 호출이 전체 전송. run 시작 시
  저장된 used_tokens가 임계 넘으면 첫 호출 전 압축. (커밋 `used_tokens`)
- **변경 0건인데 completed / `git add -A` 남의 변경 커밋**: files_changed 없으면 completed_unverified,
  자동커밋은 에이전트가 바꾼 파일만. (`a9c90b0`)
- **planner orphan tool 400**: read 루프로 tool 쌓인 세션에서 planner 컨텍스트 슬라이스가 orphan
  tool로 시작 → DeepSeek 400 → run이 조용히 죽음. 도구 이력 제외. (`4ae1ddd`)
- **chat 무검증 편집**: role에 없는 도구 호출 거부(화이트리스트). chat이 edit_file로 무검증 커밋하던 것 차단. (`3a493c1`)
- **vision 오라우팅**: has_image가 세션 전체를 봐서 옛 스크린샷이 이후 텍스트 작업까지 vision으로. 이번 턴만. (`e524e36`)
- **런타임 스모크**: verify가 build 후 self-repo 앱을 Playwright headless 로드 → uncaught 예외·핵심
  렌더 검증(`_runtime_smoke`). build는 통과하지만 런타임에 깨지는 것(showHidden 크래시)을 잡는다. (`7903550`)

**기능 완성**
- Continual Harness Refinement: P0 커널 + **applier**(승인 시 skill 파일 적용, rollback). (`daf99f9`)
- **Chat/Work 모드**: 방 단위 mode(work=검증·커밋·워크스페이스 필수 / chat=읽기전용 / ""=triage).
  triage 비용·오분류 제거. (`3b3ab41`)
- **Ox 완전 제거**: read 루프·6배 지연으로 부적합. 코드·설정·env·UI. flash로 대체. (`0eedc4b`)
- 태스크 신원 유지(중복 표시), review.py(run 리뷰 도구), 진전 기반 nudge.

**모바일 UX**
- 헤더 모드 배지 + 타이틀 탭 설정시트, 워크스페이스 피커 숨김·검색·정렬(폴더 먼저),
  대기큐 배지, 실행 배너 오버레이(스크롤 튐 제거), 하단 고정 스크롤 즉시 스냅, 세션 비용 카드 합침.

## 2. 검증 인프라 변화 (중요)
- **pytest/pytest-asyncio 설치 + pytest.ini(asyncio_mode=auto)**. 이전엔 pytest 미설치라 verify가
  test를 unavailable로 스킵 → 깨진 test가 커밋됐다. 이제 pytest 28개 + 스크립트 14개 검증.
- verify 게이트: build → pytest → **런타임 스모크(self-repo)**. 3상태(passed/failed/unavailable) 유지.

## 3. 운영 노트
- 배포·재시작은 기존과 동일(nohup uvicorn, `--reload` 없음 → 코드 변경 재시작 필요).
- **Playwright chromium**: `cd backend && .venv/bin/python -m playwright install chromium` (host 1회).
  미설치 시 런타임 스모크는 unavailable(거짓 failed 없음).
- `.env`가 config default를 덮는다 — 예산·모델 설정 바꿀 땐 `.env`까지 확인(이번 컨텍스트 버그의 교훈).
- 동시편집 금지: FORGE에 self-repo 작업 시키는 동안 사람이 편집하면 `git add`로 섞인다. 운전자는 하나.

## 4. 핵심 파일
- 런타임: `backend/app/runtime/agent.py`(_verify·_runtime_smoke·_safe_split·_compact·선제 compaction·nudge·화이트리스트)
- refine: `backend/app/runtime/refine.py` · applier `backend/app/api/routes.py::_apply_refinement_file`
- 리뷰 도구: `backend/review.py`
- 제안서: `docs/proposal/browser-computer-use.md`(런타임 스모크 1단계 구현), `prime-agent-adoption.md`(applier 구현)
