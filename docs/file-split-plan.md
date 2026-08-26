# 파일 분리 필요 대상 식별

분리 기준: (1) 단일 파일 라인 수 과대, (2) 단일 책임 위반 — 여러 도메인이 한 파일에 혼재.
측정 기준: backend/app, frontend/src 소스만, venv·node_modules·dist 제외.

## 분리 필요 (우선순위순)

| 순위 | 파일 | 라인 수 | 분리 근거 | 제안 분리 방향 |
|---|---|---|---|---|
| 1 | `backend/app/runtime/agent.py` | 3019 | 프롬프트/컨텍스트 빌딩(_load_role, _system_for, _planner_context), 실행 루프(run, _run_developer), 검증(_verify, _verify_gates, snapshot/cleanup), 메모리 추출(_extract_project_memory), 컴팩션(_precompact), 오류 분류(_classify_error)가 한 파일에 혼재 | prompts.py(시스템 프롬프트·컨텍스트), verifier.py(스냅샷·게이트·통합 검증), memory.py(메모리 추출·병합), agent.py(실행 루프만) |
| 2 | `frontend/src/App.vue` | 2179 | 채팅/세션 관리, 스킬 패널, 테마, 승인 처리, health/running 폴링, 검색·메시지 점프, 어드민, 토치 제스처가 한 파일에 혼재 | 컴포넌트 분리 — ApprovalPanel, SkillPanel, MessageList, StatusBar 등. 폴링 로직은 composable(useSessionPolling.js) |
| 3 | `backend/app/db/store.py` | 1291 | 룸/세션 CRUD, 히스토리 저장·검색, 컨텍스트/설정, 승인(create/decide/consume/expire/cancel/cleanup), ledger, 모호한 도구 처리까지 한 파일 | rooms.py, history.py, approvals.py, ledger.py로 도메인 분리 (공통 세션 획득은 db/session.py) |
| 4 | `backend/app/api/routes.py` | 1166 | fs, 채팅, 룸 CRUD, 승인, git, admin, 스킬, refinement, metrics 라우트가 전부 한 파일 | APIRouter 단위 분리 — fs.py, chat.py, rooms.py, git.py, admin.py, skills.py |
| 5 | `frontend/src/components/RoomsPanel.vue` | 765 | 세션 목록, 잡 스케줄러(createJob/toggleJob/runJobNow), 원격 MAC 화면·원격제어(screenTick/toScreenXY/입력), 스와이프 제스처가 혼재 | SidebarSessions.vue, JobsPanel.vue, MacRemotePanel.vue로 분리 |

## 부차 후보 (참고)

| 파일 | 라인 수 | 근거 |
|---|---|---|
| `backend/app/tools/registry.py` | 653 | 도구 등록 + BLOCKED_COMMANDS 등 정책이 한 파일. 정책을 policy.py로 분리 가능 |
| `backend/app/agents.py` | 297 | 규모는 작으나 역할별 에이전트 정의가 응집 — 현재로는 분리 불필요 |

## 분리 시 주의

- agent.py는 `_load_role`이 docs/agents/*.md를 매 호출 읽는 구조라 프롬프트만 이동하면 안 된다(변경 시 동작 검증 필요).
- store.py 함수는 routes.py·agent.py 등 다수 호출부가 있어 change-impact-analysis로 호출부를 먼저 확인한다.
- 분리는 동작 변경 없이 구조 이동만 하고, backend pytest와 frontend npm build로 회귀를 잡는다.
