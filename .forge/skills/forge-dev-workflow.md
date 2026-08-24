# FORGE 개발 워크플로우

FORGE 자체 코드를 수정할 때 따르는 절차. "고치고 끝"이 아니라 검증까지 한다.

## 프론트엔드 (frontend/)
1. `frontend/src/App.vue` / `frontend/src/style.css` 소스를 수정한다.
2. 빌드로 반영: **`build_frontend` 도구를 호출한다.** (host에서 `npm run build`가 돌아
   dist가 갱신·배포된다. `bash`로 `npm run build`를 하지 마라 — 샌드박스엔 node가 없다.)
   결과에 "빌드 성공"이 나오는지 확인하고, 실패하면 에러를 고쳐 다시 호출한다.
3. `frontend/dist/**`(minified 번들)는 **손으로 수정하지 않는다** — `build_frontend`로만 갱신.
4. 색은 하드코딩하지 말고 CSS 토큰(`var(--bg)`, `var(--panel)`, `var(--accent)` 등) 사용.

## 백엔드 (backend/)
1. `backend/app/**` 수정.
2. syntax 확인: `python3 -c "import ast; ast.parse(open('backend/app/....py').read())"`.
3. **재시작은 하지 마라.** `pkill`·`kill`·`uvicorn`은 BLOCKED_COMMANDS라 실행되지 않는다
   (자기를 실행 중인 프로세스를 죽이는 자멸 방지). 백엔드 변경을 적용하는 재시작은 사람이/
   슈퍼바이저가 한다. 재시작이 필요하면 최종 보고에 "백엔드 재시작 필요"라고 남긴다.
4. 검증은 재시작 없이 되는 것으로 한다: `cd backend && ./.venv/bin/python -m pytest -q`
   (venv 필수 — psycopg). 런타임 로직(루프·회복·압축 등)은 결정적 테스트로 검증한다.
5. 헬스 확인이 필요하면 `curl -s http://localhost:8790/api/health` → `{"ok":true}`.
   단 이건 **재시작 전 구버전** 응답이다 — 이걸로 내 변경이 반영됐다고 판단하지 마라.

## 비파괴 원칙
- 대화/히스토리 등 사용자 데이터를 유실시키지 않는다(사용자 메시지는 수신 즉시 저장).
- 표시/저장용 원본과 모델 전송용 컨텍스트를 분리(compaction·pruning은 모델 쪽만).
