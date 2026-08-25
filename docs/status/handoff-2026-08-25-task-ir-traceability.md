# 세션 인수인계 — Phase 0/1 (Task IR + Requirement Traceability) (2026-08-25)

> 사용자가 FORGE 진화 master prompt(Phase 0–9)를 건넸다. "wholesale rewrite 금지,
> code가 authority, phase마다 독립 검증, 실패 시 다음 phase 금지"가 핵심 제약.
> 이 세션은 Phase 0(결함) + Phase 1(Task IR/traceability)을 검증 완료했고, Phase 2 이후는
> **이미 구현돼 있어 재작성하지 않는다는 판단**까지 내렸다.

## 0. TL;DR — 다음에 할 일

**"Phase 9까지 소진"이 목표가 아니다.** 판단 기준은 번호가 아니라 *측정된 가치*. 남은 것 중:

- **planner 비용 병목 실측·완화** — 가장 값어치 큼. 메모리(`cost-bottleneck-planner`)상 planner가
  실제 달러의 73%, 원인은 마라톤 세션 히스토리 재전송. speculative 아님, 이미 새는 돈.
- **Task IR/traceability를 실제로 켜서 관찰** — 지금 default-off라 값이 안 보인다. `TASK_IR_ENABLED=1`로
  켜서 실제 세션에서 traceability 이벤트/false_completion 후보가 유의미한지 관측 → A/B 후 라우팅에 쓸지 결정.
- **write-only checkpoint 결정** — 별도 태스크로 이미 플래그됨(아래 6번). rollback 배선 or 제거.

지금 **안 하는** 이유(YAGNI/보류):
- Phase 2 durable 상태기계 신규 구현 — per-step history + resume이 이미 동작·테스트됨. 재작성=손해.
- Phase 3 capability isolation — allowed_tools 하드리젝트 + reviewer read-only 이미 있음.
- Phase 4 provider adapter — MODEL_PRICING 이미 분리됨. DeepSeek 스펙은 미검증이라 추측 금지.
- MCP/Skills 표준 호환 — 외부 도구를 실제 붙일 일이 생기면 그때. 지금은 YAGNI.
- 새 상태기계·multi-agent 확장 — 깨지는 게 없으면 안 짓는다.

## 1. 이번 세션에 한 것 (전부 push, main)

**Phase 0 — 결함 5종** (이전 커밋들: `63df945`·`c178784`·`d142219`·`e72ecae`·`4bc98c8` 등)
- `python-multipart` requirements 누락 보강(FastAPI 업로드 런타임 의존). frontend `test` script.
- config 컨텍스트 예산 분리(working/hard/output/compaction/emergency), `logical_budget` 하위호환 유지.
- fail-closed 기동 게이트(`assert_startup_auth`), CORS origin 화이트리스트(`parse_allowed_origins`).
- lifespan 재구성: 필수 DB init 실패 시 `app.state.ready=False` + `/api/ready` 503, resume/scheduler 스킵.
- **Reviewer read-only**: `_ROLE_TOOLS["reviewer"]` → `READ_ONLY_TOOL_SCHEMAS`(리뷰어가 코드 못 고치게).

**Phase 1 — Task IR + Requirement Traceability** (`bf38288`·`6290ed0`·`c3e250b`·`ce71551`·`35cbd45`)
- `task_ir.py`: 원문→구조화 요구사항(R1,R2… 안정 ID), **원문이 authority**, 실패 시 None fallback.
  저비용 flash 1콜. `_maybe_interpret`(agent.py) — **기본 off**, 켜지면 `task_ir` 이벤트 발행.
- `traceability.py`: `compute_traceability(requirements, gates)` 순수 함수. requirement↔gate 대조로
  **false_completion 후보**(요구사항 놓친 채 완료) 탐지. completion authority 아님, 관찰 지표.
- gate↔requirement 링크: `update_gates` 도구에 `requirement_id`(선택), `merge_gates`/`replace_gates`가
  DB까지 왕복 보존. `acceptance_gates.requirement_id` 컬럼 + idempotent ALTER(main.py `_COLUMN_PATCHES`).
- 완료 배선: `_maybe_interpret`가 요구사항을 세션 키로 보관(`self._task_ir_reqs`, in-memory) →
  run() 완료 시 gate와 대조해 `traceability` 이벤트 발행(pop으로 누수 방지).

**전 경로 default-off/관찰 전용** — 기존 API·DB·PWA·모바일 기능 불변.

## 2. 검증 상태 (중요)
- **pytest 205 passed / 회귀 0**. 세션 시작 161 → 200(Phase 0/1) → 205(end-to-end).
- 신규 테스트: `test_reviewer_capability`·`test_context_budget`·`test_task_ir`(10)·
  `test_task_ir_integration`(7, end-to-end 포함)·`test_traceability`(5)·`test_gate_requirement_link`(2).
- **end-to-end 회귀**: `make_rt` 하네스로 실제 run() 구동 → flag ON이면 done과 함께 traceability 발화
  (false_completion·unverified=[R2]), flag OFF면 무발화. flag 뒤 dead code 아님을 증명.
- 검증 원칙 준수: 테스트 삭제·완화·skip 없음. Reviewer 변경 시 옛 버그 기대값을 **수정**(약화 아님).

## 3. 운영 노트
- **Task IR 켜는 법**: `TASK_IR_ENABLED=1`(config `task_ir_enabled`). off면 어댑터 호출 자체가 없어 비용 0.
- 재시작 필요(코드 변경, `--reload` 없음). `.env`가 config default를 덮는다 — 설정 바꿀 때 `.env`까지 확인.
- 동시편집 금지: FORGE에 self-repo 작업 시키는 동안 사람이 편집하면 `git add`로 섞인다. 운전자는 하나.
- 커밋·푸시는 **명시 요청 시에만**(rule 11). 이번 세션은 사용자 "고"로 push 승인됨.

## 4. 핵심 파일
- Task IR: `backend/app/runtime/task_ir.py` · traceability: `backend/app/runtime/traceability.py`
- 배선: `backend/app/runtime/agent.py`(`_maybe_interpret`·`self._task_ir_reqs`·완료 글루 gate_coverage 직후)
- gate 링크: `backend/app/db/store.py`(`merge_gates`·`replace_gates`·`_gate_dict`) ·
  `backend/app/tools/registry.py`(update_gates 스키마) · `backend/app/db/models.py`(AcceptanceGate.requirement_id)
- 제안서: `docs/proposal/intent-interpreter-task-ir.md`

## 5. Phase 2+ 실태 (재작성 금지 근거)
- **durable execution 이미 있음**: `agent.py:1049` per-step `save_history`(중단돼도 완료 스텝 보존),
  `store.take_interrupted_runs`(running=True 잔류 회수), auto-resume(저장 history + 권한/모델티어 복원).
  `test_reliability_invariants`가 resume 복원 검증.
- **capability isolation 부분 있음**: `allowed_tools` 하드리젝트(`agent.py:1237`), reviewer read-only.
- **pricing 분리됨**: config `MODEL_PRICING` resolver.

## 6. 열린 태스크 (플래그됨)
- **Checkpoint write-only** (`task_313176c8`): `save_checkpoint`가 승인형 도구 전 (git_sha, step) 기록하나
  전 계층에서 `select(Checkpoint)` 없음 — rollback 소비자 부재. (A) 실패 시 마지막 정상 스텝 rollback 배선
  (git reset은 비가역 → 승인 게이트·미커밋 보존 필수) or (B) dead capability 제거. **요청 없이 짓지 않음.**
