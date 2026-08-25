# 세션 인수인계 — 신뢰성 하드닝 (2026-08-26)

> 목표: FORGE를 "현업 5년차가 GitHub issue를 맡기고 자리를 비워도 되는" 신뢰 가능한
> coding agent harness로. 기능 추가가 아니라 **신뢰성·검증가능성·반복가능한 실전 성공률**.
> 우선순위: verified correctness → verified completion → user trust → cost_per_verified_task
> → elapsed → human intervention. DeepSeek 저가 API를 강한 harness로 감싼다.

## 0. 먼저 읽어라 (긴 히스토리 재전송 금지)
1. 이 문서 — 이번 세션에 한 것 + 다음 P0 + 재작성 금지 근거.
2. 판단 우선순위: **코드 > 테스트 > docs/core > docs/status > proposal**. proposal을 구현
   사실로 간주하지 말 것.
3. 관련 메모리: `cost-bottleneck-planner`(reasoning 제거는 계약 위반 — 되돌림),
   `forge-process-reliability`, `forge-verify-and-config-traps`, `forge-rsi-self-edit-hazard`.

## 1. 현재 상태 (검증됨, 전부 push · main HEAD = 88b4963)
- **전체 pytest 237 passed / 회귀 0**. ruff(E9,F) 통과. frontend build·node --test 통과.
- clean venv `pip install -r requirements.txt` exit 0(재현성).
- 서버 재시작됨(uvicorn). approvals 테이블 create_all로 생성 확인.

## 2. 이번 세션에 한 것 (push, main)

### 신뢰성 하드닝 4단위
- **`e70e38f` bench 신뢰성 지표**: benchmark가 deterministic checker만 봐 '실제 성공률'을
  증명 못 하던 것을, FORGE 완료 주장 × checker **confusion matrix**로. `_run_one`이 done
  이벤트 status 캡처, `aggregate`가 산출:
  - **verified_success_rate** = completed(_unverified) AND checker PASS
  - **false_completion_rate** = completed AND checker FAIL (gate 자기검증 실패 — 최악)
  - **cost_per_verified_task** = 총비용/verified (verified 0이면 None)
  - false_failure_rate·상태분해·pro_escalation·context_block·intervention/task·tool_calls/task·
    prompt/completion/cache 토큰·elapsed avg/p50/p95. 토큰 절감≠성공(gate: verified 기준).
  - 산식 self-test(`bench.py --self-test`) + pytest(script suite)로 고정. **실측은 `--run`
    (LLM 비용) 필요 — 미실행**.
- **`a4dcecd` CI + pinning + lint**: `.github/workflows/ci.yml`(backend: pinned install→ruff
  →bench self-test→pytest+postgres / frontend: npm ci→node --test→vite build). requirements
  버전 고정(+누락 pywebpush 보강). ruff 점진(E9,F만, 스타일 제외). 유료 벤치는 CI 제외.
- **`c8025f5` 테스트 약화 gap**: `change_guard`가 이미 삭제/라인순감소(numstat)·민감파일을
  비차단 감지·배선 중이었다. **gap: skip/xfail/only 우회는 numstat로 못 잡음** → `detect_skipped_tests(diff)`
  추가(테스트 파일+추가라인 한정, 오탐 억제). 비차단 evidence(정당 리팩터 자동차단 안 함).
- **`88b4963` resume 중복 실행 방어**: save_history가 스텝 시작에만 있어, side-effect 도구
  완료 후 다음 스텝 save 전 crash 시 resume이 재실행(write 중복·bash 부작용·git 중복 커밋).
  **side-effect 도구(=APPROVAL_REQUIRED) 실행 직후 즉시 save_history** → crash 창 제거.
  end-to-end 테스트에 save 시퀀스 spy로 runtime path 검증.

## 3. 다음 할 일 — P0부터 (측정된 가치 순, 번호 소진 아님)

**P0 (신뢰성 직결, 미해결)**
1. **Gate traceability를 완료 판정에 반영** — 현재 `traceability.py`(compute_traceability)는
   관찰 전용(이벤트만), 완료 차단 미배선. Task IR ON일 때 false_completion_candidate면
   `completed`→`completed_unverified`로 **강등**(차단 아님 — false-block 위험 회피). Task IR은
   default off(`TASK_IR_ENABLED`)라 실효는 ON 전제. 배선: `_maybe_interpret`가 보관한
   requirement(`self._task_ir_reqs`) + gate 대조 → completion_policy에 반영.
2. **execution ledger (완전 idempotency)** — 즉시-save로 crash 창을 거의 없앴으나
   tool 완료~즉시save 사이 극소 window 잔존. 완전 방어는 (run_id, step, tool_call_id,
   args_hash, started/completed, result) 기록 + resume 시 started-but-not-completed(ambiguous)면
   **자동 재실행 금지**(문서 §7). event-sourcing 전체는 만들지 말 것 — 최소.

**P1**
3. **실측 벤치 1회** — `bench.py --run`(LLM 비용)으로 verified_success_rate/false_completion_rate/
   cost_per_verified_task baseline 측정. 변경 전/후 비교의 기준선. **사용자 비용 승인 필요.**
4. reasoning/write-folding variant 벤치(§6): baseline vs 최적화 ON. 성공률 유의하게 떨어지면 rollback.

**P2**
5. `agent.py`(2874줄) 안전 분리(§5) — 테스트 고정 후 작은 단위로(context/prompt_builder/
   tool_loop/verification). 기능 변경과 동시에 하지 말 것.
6. §2B unrelated change 3분류(expected/supporting/suspicious) — false-block 위험 커 신중.
   §10 provider capability 확대. adversarial task(§3): regression-preservation 등 보강.

**안 하는 것 (금지·YAGNI)**: 새 agent 역할·multi-agent 확대·vector DB/RAG·전체 TS 전환·
checkpoint 재도입·reasoning 무조건 삭제·write/tool history 무조건 삭제·토큰 절감 우선 최적화·
proposal만 쓰고 미구현·테스트 숫자만 늘리고 runtime path 미검증.

## 4. 핵심 파일
- 지표: `backend/bench.py`(aggregate confusion matrix)·`backend/bench_tasks.py`(25 task, deterministic checker)
- 테스트 약화: `backend/app/runtime/change_guard.py`(detect_test_weakening·detect_skipped_tests·
  detect_sensitive_changes) · 배선 `agent.py` 검증 단계
- resume 방어: `agent.py`(`_SIDE_EFFECT_TOOLS`, tool result append 직후 save_history)
- traceability(P0-1): `backend/app/runtime/traceability.py` · `task_ir.py` · `completion_policy.py`
- CI: `.github/workflows/ci.yml` · lint `backend/ruff.toml`
- 승인(직전 세션 완료): `approvals.py`·`db/store.py`(create/decide/consume/cancel/cleanup_orphan)

## 5. 재작성 금지 근거 (이미 있음)
- Durable Approval **정합성까지 완료**(재시작 orphan cleanup·자동승인 PG·취소·만료·결정 경쟁·
  run_id). reasoning replay는 **capability 기반**(thinking+tools면 유지 — DeepSeek V4 계약).
  write folding은 **성공한 과거 write만·최근 밖만·원본 보존·전송 projection만**. Context tree·
  compaction·tool_store/pruning·auto commit gate(verification_failed→금지)·host blocklist.
  **이것들 재구현·공격적 축소 금지.**

## 6. 운영 노트
- 커밋·푸시는 **명시 요청 시에만**. 이번 세션은 사용자 "푸쉬하고" 승인.
- 서버 재시작 시 코드 반영(--reload 없음). `.env`가 config default를 덮음.
- 검증 함정: 전체 pytest가 subprocess 다수 + 실행 중 uvicorn과 **DB 커넥션 경합** 시 느려짐/
  hang처럼 보임. 배경 uvicorn·중복 pytest를 정리하면 정상(~30s). `kill -9`한 uvicorn이
  running=True 세션을 남기면 lifespan auto_resume가 실제 LLM run을 돌려 hang — DB running 리셋.
- resolve_pending_approvals·task_facade.cancel은 **async**(PG 전이 포함) — 호출부 await 필수.
