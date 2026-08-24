# Agent Crew / Roster

게임 캐릭터 선택 화면처럼 꾸민 **Agent Inspector** 패널. 표시되는 정보는 실제 Runtime과
연결돼 있다(정적 스킨이 아니라 실행 중 역할·모델·도구 정책을 읽어온다).

## 보여주는 것

- 4개 역할(Developer / Planner / Reviewer / Chat)의 프로필 카드.
- 역할별 담당 모델·thinking 정책·도구 목록·capability·fresh/readonly 여부.
- Prompt Viewer: 각 역할의 실제 시스템 프롬프트(`docs/agents/*.md`) 원문 조회.

## 정보 출처 (모두 Runtime에서 파생)

- 역할 정의: `backend/app/runtime/agent.py` (`_load_role` — `docs/agents/*.md`를 매 호출
  읽으므로 프롬프트 수정 시 재시작 불필요).
- 모델 정책: `backend/app/orchestrator/model_router.py` (`ModelRouter`).
- 도구 스키마·승인 정책: `backend/app/tools/registry.py` (`TOOL_SPECS`).

## API (읽기 전용)

- `GET /api/agents` — roster 목록 (secret 없음, `active_role` 포함).
- `GET /api/agents/{role}` — 단일 역할 상세 (도구 스키마 + 정책 노트).
- `GET /api/agents/{role}/prompt` — 역할 시스템 프롬프트 원문.
  - 목록에 없는 role은 404. 내부용 role(`triage`, `vision`)은 roster에 노출하지
    않는다(프롬프트도 404). `gate_recovery`는 회복 전용 role로 prompt가 존재하지만
    기본 roster에서 제외된다.

## 프론트엔드

- `frontend/src/components/AgentCrewPanel.vue` — 캐릭터 선택 스타일 패널.
- 메뉴에서 "에이전트"로 진입. 스타일은 `frontend/src/style.css`의 `--crew-*` 토큰.

## 검증

- 단위/API 테스트: `cd backend && ./.venv/bin/python -m pytest -q test_agents.py`.
- 브라우저 스모크: `cd backend && ./.venv/bin/python probe_agents_ui.py`
  (백엔드 8790 기동 상태에서). 성공 시 `CREW_SMOKE_OK` 출력.

## 참고

- "현재 작업 중" 표시 등 실행 중 세션 상태 연동은 아직 정적이다 — 병렬 Worker 확장 시
  Runtime session 스냅샷을 추가로 노출하면 된다.
