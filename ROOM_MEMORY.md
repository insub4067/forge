
## 학습된 프로젝트 지식 (FORGE 자동 적립)

> 이것은 검증된 작업에서 축적한 **보조 정보**다. 현재 소스·설정과 충돌하면 반드시
> 현재 소스를 따른다. 아래 항목도 작업 전에 실제 파일로 확인한다.

- 원격 마우스/키보드 입력은 `POST /api/mac/input`으로 전달된다(터미널의 WebSocket과 무관).
  - source: `frontend/src/components/RoomsPanel.vue`
- 원격 화면 좌표 변환은 `toScreenXY()`/`containContentRect()`를 쓴다. `object-fit: contain`
  레터박스와 portrait의 `rotate(90deg)`를 함께 보정해야 한다.
  - source: `frontend/src/lib/screenCoord.js`
- 원격 화면은 단일 프레임 폴링이다(스트리밍 아님). 갱신 주기는 `screenTick`의 setTimeout.
  - source: `frontend/src/components/RoomsPanel.vue`
- 원격제어를 켜면 컨트롤 바를 숨겨 터치 영역을 확보한다(`macControls`). 꺼져 있을 때는
  화면 탭으로 표시/숨김을 토글한다.
  - source: `frontend/src/components/RoomsPanel.vue`
- 순수 로직(좌표 변환·드래그·throttle)은 `frontend/src/lib/`에 분리하고
  `cd frontend && node --test src/lib/<name>.test.js`로 검증한다(의존성 없음).
  - source: `frontend/src/lib/moveThrottle.test.js`
- 백엔드 테스트는 `cd backend && ./.venv/bin/python -m pytest -q`로 돌린다(venv 필수 — psycopg).
  - source: `backend/pytest.ini`
- `docs/agents/*.md` 역할 프롬프트는 `_load_role`이 매 호출 파일에서 읽으므로 캐시가
  없다 — 프롬프트만 고쳤으면 백엔드 재시작이 필요 없다(`app/**` 변경은 필요).
  - source: `backend/app/runtime/agent.py`
- `pkill`·`kill`·`uvicorn`은 BLOCKED_COMMANDS다 — 에이전트가 백엔드를 재시작할 수 없다
  (자기 세션 자멸 방지). 재시작이 필요하면 보고에 남긴다.
  - source: `backend/app/tools/registry.py`
