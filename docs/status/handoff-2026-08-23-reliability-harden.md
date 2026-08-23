# 세션 인수인계 — 신뢰성 경계 강화 + Prime 도입 검토 (2026-08-23)

> 다음 세션은 이 문서로 시작한다. 핵심: **신뢰성 경계 8종 강화 완료**, Prime 도입 B는 근거 기반 기각,
> **다음 작업은 A(Continual Harness Refinement) P0 커널**이다.

## 0. TL;DR — 다음에 할 일

**A. Continual Harness Refinement의 P0 커널**부터 시작한다(제안서 `docs/proposal/prime-agent-adoption.md`).
자동수정은 아직 하지 말고, **뼈대만**:
1. `RefinementCandidate` 모델(type/scope/proposed_change/evidence_runs/failure_pattern/expected_effect/created_at) + before/after history + rollback.
2. run 종료 시 근거 수집(verification 결과·repeated failure·repair 활성·cost_per_success 연결).
3. 투명 승인 UX(작업 후 "학습 후보" 표시 → 승인/무시, Global 영향은 승인 기본).
4. 적용 대상은 **Learned/Project Skill·supplemental prompt부터**(Base Prompt는 version-controlled 불변, supplement만).
5. 각 단계는 기존 deterministic benchmark로 전후 비교. LLM-as-judge 금지.

**하지 말 것**: 새 Agent, vector DB, MCP 추상화, distributed worker, 자동 main merge, evidence 없는 prompt 자기수정, 자동 Global Skill 오염, 비용 위해 verification 약화.

## 1. 이번 세션에 한 것 (전부 push됨)

**신뢰성 경계 강화 `a0372de` (harden)** — "모델을 믿지 말고 프로세스로 검증"을 경계까지:
- **권한 invariant(최우선)**: 세션 `auto_approve`를 DB에 영속화(Session 컬럼+`_COLUMN_PATCHES`), durable resume가 **저장값 복원**(True 강제 제거). "재시작해도 권한 불확대" — 원래 수동승인이면 재개 후 새 위험작업은 approval에서 pause.
- **Verification 3-state**: `passed`/`failed`/`unavailable`. "검증 못 함"을 "성공"으로 기록 안 함(→`completed_unverified`). `failed`→커밋 금지. node_modules 없으면 build는 unavailable(거짓 failed 방지), pytest 미설치도 unavailable.
- **Commit invariant**: `_autocommit`은 `finish()`의 `completed`/`completed_unverified`에서만(우회 경로 0). `verification_failed`·run 예외·resume 실패 → 커밋/push 안 됨.
- **칸반 invariant**: 모델은 `todo`/`working`만(스키마 enum + `_clamp_task_status`). `testing→done`은 프로세스만(`_mark_testing`+`_finalize_tasks`). 4단계 = todo→working→testing→done.
- **Resume 강건성**: 잘못된 workspace(루트 `/`·없음) 재개 안 함 + 20분 타임아웃. 크래시 루프 가드(`final_status=resuming`).
- 결정적 테스트 `backend/test_reliability_invariants.py` 추가.

**부수 수정**:
- `0590c1b` bash 타임아웃이 자식까지 종료(`start_new_session`+`os.killpg`) — orphan `find /` 누수 방지. `test_sandbox_timeout.py`.
- `20ded50` 세션 생성 시 루트 `/` 워크스페이스 차단(전체 디스크 스캔 방지).
- git push 권한을 FORGE에 부여(`BLOCKED_COMMANDS`에서 제거, kill/uvicorn은 유지).

**Prime 도입 B(Restricted Tool Script/`explore`) — 근거 기반 기각 `d6385b1`**:
- 만들고 벤치 → 모델이 explore 안 씀. **FORGE는 이미 여러 tool_call을 한 턴에 병렬 실행**(`READ_ONLY_TOOLS` prefetch, agent.py ~948)하므로 배치 도구가 중복. → 되돌림.
- 결론: 4개 도입안 중 B는 FORGE에 이미 내장. C(bounded workers)는 동시편집 충돌 위험(후순위·worktree 격리 필수). D(budget)는 step/escalation 상한 이미 있고 cost/wall-time 예산만 빠짐. **A가 진짜 상.**

## 2. 지금 프로세스가 보장하는 것 (실측 검증됨)
- 완료 = 검증(test/build) 통과. 모델 "됐습니다"로는 완료 안 됨.
- 검증 실패 코드는 커밋/push 안 됨. 실패 시 1회 수리 재시도(bounded).
- 성공 시 자동 commit+push(`AUTO_COMMIT=0`로 끔).
- 스텝마다 history 저장 → 중단돼도 유실 없음. 재시작 시 auto-resume 무인 완주(`AUTO_RESUME=0`로 끔).

## 3. 운영 노트 / gotcha
- 배포: 맥에서 직접 `uvicorn app.main:app --host 0.0.0.0 --port 8790`, cloudflared 터널. `--reload` 없음 → 코드 변경은 **재시작해야 반영**. 재시작은 **nohup 필수**(맨 `&`는 셸 종료 시 죽어 서버 완전 다운):
  `cd backend && nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790 > /tmp/forge-backend.log 2>&1 &`
- `SANDBOX_MODE=host` — bash가 호스트에서 직접 실행. FORGE의 `bash`는 self-repo도 건드릴 수 있음.
- **동시편집 금지**: FORGE에 자기 repo(`/Users/insub/Desktop/forge`) 작업 시키는 동안 사람이 같은 파일 편집하면 충돌. 재시작·수정 전 **항상 `/api/sessions/<id>/status`로 running 확인**.
- 진단 시 `curl --max-time 3`은 서버 바쁠 때(Ox 느림·balance fetch·폴링 폭주) 거짓 timeout(HTTP 000). **10초+로 재확인** — 이번에 "hang" 오진의 원인.
- Ox(OpenRouter `stealth/ox-alpha`)는 매우 느림(6배). triage는 항상 flash(티어 무관). 모델별 라우팅 변경은 **벤치 없이 금지**(제안서 원칙).

## 4. 남은 위험 (다음 세션에서 볼 것)
- `/api/rooms`가 `final_status` 미노출(표시 버그 — DB·집계는 정상).
- `completed_unverified`는 성공 집계에 안 잡힘(의도 — 정직하나 단순작업 undercount 가능).
- balance fetch가 매 폴링마다 DeepSeek 호출 → 순간 지연. 캐시 여지.
- resume가 model_tier는 복원 안 함(auto_approve만). 재개는 auto로 돎(권한 아님 — 무해).

## 5. 핵심 파일
- 런타임: `backend/app/runtime/agent.py`(run 루프·검증 게이트·finish·_verify·_autocommit·_finalize_tasks·_clamp_task_status)
- 라우트: `backend/app/api/routes.py`(chat·resume_run·git)
- 부팅: `backend/app/main.py`(lifespan·auto-resume·_COLUMN_PATCHES)
- 도구: `backend/app/tools/registry.py`(TOOL_SCHEMAS·execute_tool·BLOCKED_COMMANDS)
- 샌드박스: `backend/app/sandbox/executor.py`
- 테스트: `backend/test_reliability_invariants.py`·`test_reliability_gates.py`·`test_sandbox_timeout.py` 등
- 제안서: `docs/proposal/prime-agent-adoption.md`

## 6. 커밋 SHA (이번 세션 주요)
`a0372de` 신뢰성 강화 · `0590c1b` orphan-kill · `20ded50` 루트 ws 차단 · `d6385b1` explore 기각 · 병합 `cc23ce4`. origin/main 동기화, 미push 0.
