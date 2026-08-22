# FORGE 개발 워크플로우

FORGE 자체 코드를 수정할 때 따르는 절차. "고치고 끝"이 아니라 검증까지 한다.

## 프론트엔드 (frontend/)
1. `frontend/src/App.vue` / `frontend/src/style.css` 수정.
2. 빌드로 검증: `npm --prefix frontend run build` (에러 없어야 함).
3. 색은 하드코딩하지 말고 CSS 토큰(`var(--bg)`, `var(--panel)`, `var(--accent)` 등) 사용.
4. 서버가 `frontend/dist`를 서빙하므로 빌드만 하면 앱 새로고침 시 반영(백엔드 재시작 불필요).

## 백엔드 (backend/)
1. `backend/app/**` 수정.
2. syntax 확인: `python3 -c "import ast; ast.parse(open('backend/app/....py').read())"`.
3. 재시작: `pkill -f "uvicorn app.main"; sleep 1; (cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790 &)`.
4. 헬스: `curl -s http://localhost:8790/api/health` → `{"ok":true}`.
5. 런타임 로직(루프·회복·압축 등)은 결정적 테스트로 검증 — `backend/test_review_loop.py` 패턴 참고.

## 비파괴 원칙
- 대화/히스토리 등 사용자 데이터를 유실시키지 않는다(사용자 메시지는 수신 즉시 저장).
- 표시/저장용 원본과 모델 전송용 컨텍스트를 분리(compaction·pruning은 모델 쪽만).
