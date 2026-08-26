# FORGE — Current Work Status

> Source audit: 2026-08-26 `main` `143e378`까지 확인. 이 문서는 Current State authority이며 proposal/handoff보다 우선한다.

## 2026-08-26 세션 업데이트 (신뢰성)

- **Task IR 기본 ON**(`TASK_IR_ENABLED=True`). requirement(R1..)를 gate와 `requirement_id`로
  대조해 미검증이면 완료를 `completed`→`completed_unverified`로 강등(차단 아님). 인터프리터는
  코드 경로에서만 실행(대화 턴 제외). 실측 n=3(75 run): verified_success 0.92→0.973,
  false_completion 0.04→0.027, 완전검증 완료 0→10, verified당 비용 +6%.
  `bench-baseline-2026-08-26.md`.
- **side-effect 실행 장부**(`tool_ledger`): 도구 실행 전 started, history 저장 후 completed.
  resume이 '실행 여부 불명'(started 잔존) 부작용을 자동 재실행하지 않는다(1회 경고 후 진행).
- **CI 상시 실패 해소**: pytest용 스키마 초기화(conftest) + gate 검증 `SANDBOX_MODE=host`.
  이전엔 fresh postgres 스키마 없음 + docker 이미지 없음으로 계속 빨간색이었다. 지금 초록.
- pytest **272 passed**(host mode, forge_test 격리 DB), ruff `.` 통과, bench self-test 통과 —
  기준 SHA `32efec6`(2026-08-26). read-only 완료(Git evidence)·게이트 검증 격리(P0-B) 반영.
- **다음 큰 건**: Persistent execution(independent durable worker/queue) — `durable-worker-resume`
  partial. Provider independence는 index상 deferred/rejected-experiment이지 다음 P0가 아니다.

## 현재 한 줄 요약

FORGE는 **DeepSeek를 두뇌로 쓰되 완료 여부는 Harness가 실제 evidence로 판정하는 self-hosted coding runtime**으로 수렴하고 있다. 현재 단계는 기능 수 확장보다 dogfooding으로 신뢰·사용감·오개입을 줄이는 단계다.

## 현재 completion path

```text
User goal
→ chat/work routing
→ simple Developer | complex Planner→Developer→fresh Reviewer
→ Acceptance Gate coverage
→ Generic Verification
→ Acceptance Verification
→ Integration Verification
→ deterministic CompletionSummary
→ completed / completed_unverified / verification_failed / ...
```

핵심 불변식:

- 코드 변경 + gate 0 → `completed` 불가.
- Gate Recovery는 1회 안전망일 뿐 정상 경로가 아니다. Developer가 구현 전에 gate를 만든다.
- `completed_unverified`는 auto push 금지.
- 모델 self-report는 completion evidence가 아니다.
- current source가 memory보다 우선한다.

## 자기 핵심 경로 프로브

단위 테스트는 함수를, 실제 버그는 **경로 이음새**(요청→핸들러→store→모델→응답)에서
난다. `backend/probe.py`가 그 이음새를 라이브 서버 대상으로 검사한다.

```bash
cd backend && ./.venv/bin/python probe.py          # 무비용 이음새 검사(서버만 필요)
cd backend && ./.venv/bin/python probe.py --full    # + 실제 세션 1회(비용·비결정적)
```

무LLM 검사(health·폭주 응답성·모델 티어 세션별·이미지 인라인)는 `test_probe_smoke.py`로
pytest에도 편입돼 서버가 떠 있으면 자동으로 돈다(없으면 skip). `--full`은 실제 코드 작업을
격리 워크스페이스에서 돌려 gate 생성·완료 보고 형식·자동 커밋·프로젝트 메모리 provenance
까지 확인하고 정리한다. 오늘 나온 이음새 버그들(이미지 미전달·워크스페이스 유령 id·압축
유실·grep/list_dir 폭주)이 이런 프로브 하나면 잡혔을 것들이다.

## 최근 완료된 중요한 hardening

### Acceptance / completion

- Gate Ledger와 process-owned status/evidence.
- gate command host-shell bypass 제거 → `DockerSandbox.run_verify()`.
- Developer prompt에서 gate를 구현 전 step 0으로 앞당김.
- gate 0 code run의 1회 recovery + fallback `completed_unverified`.
- gate quality anti-pattern(`grep` 존재 확인, generic pytest 재탕, 작업 수단을 gate로 등록) 지침 강화.
- CompletionSummary deterministic formatter + 새로고침 후 history persistence.
- generic unavailable인데 “최종 회귀 확인”이라고 말하던 report 모순 제거.

### Context

- large file symbol map + `find_symbol`.
- tool result pruning/store/retrieval.
- fresh Planner/Reviewer context + 파생 context `persist=False`.
- 131k logical budget, 75% compaction, 95% hard block.
- compaction summary를 DB에 영속해 run 경계를 넘어 재사용.

### Project Memory

실제 오염 사례(HTTP remote input을 WebSocket/WebRTC라고 기억)가 발생해 memory를 harden했다.

현재:

```text
passed gate/evidence + changed files
→ utility model candidate {fact, source, evidence}
→ memory_guard deterministic validation
→ accepted fact만 ROOM_MEMORY
```

source path/evidence/changed-file 관계/unsupported claim/duplicate를 검사하고 rejected 이유를 event로 남긴다. 기존 ROOM_MEMORY도 소스와 대조해 정화했다.

### Session / UX

- auto_approve와 model_tier를 세션별 DB authority로 통일.
- room 전환 시 해당 세션 설정을 UI로 복원.
- 모델 티어 `pro` 경로를 regression test로 고정.
- activity 상태를 상단 카드 하나로, task 진행을 하단 task-bar 하나로 정리해 중복 표시 제거.
- 모바일 swipe/pull-to-refresh/remote pointer UX 개선.

### Evaluation / RSI

- R0 deterministic benchmark 25 tasks.
- script-style tests가 pytest에서 조용히 누락되던 사각 제거.
- R1 candidate worktree/self-mod/benchmark/report/human promotion 구현.
- no-op candidate는 benchmark 전에 REJECT.

### Automation / Remote / MCP

- Scheduled one-shot/daily/interval + timezone + durable next_run_at + atomic claim + retry.
- MCP stdio execute/status/result/cancel.
- Mac host PTY terminal, screen polling, pointer/keyboard input, camera PoC.
- auth token 사용 시 uploads까지 보호.

## 현재 provider truth

`backend/app/llm/factory.py`는 **DeepSeek adapter만** 지원한다. OpenRouter/Ling은 실험 후 repeated-tool behavior 문제로 main에서 되돌렸다. On-prem/OpenAI-compatible provider는 proposal이지 현재 기능이 아니다.

## 알려진 위험 / 관찰 항목

### 1. Gate semantic quality

Gate 존재 문제는 크게 줄었지만 시험 문제 자체는 여전히 모델이 작성한다. weak gate가 실제 사용자 요구를 충분히 대표하는지는 deterministic benchmark/external checker와 비교하며 측정해야 한다. false PASS뿐 아니라 잘못된 gate로 맞는 코드를 막는 false-negative도 관찰한다.

### 2. Memory guard의 보수성

Evidence binding은 거짓 durable memory를 크게 줄였지만 semantic proof engine은 아니다. token/source 기반 guard는 valid fact를 거절할 수도 있고 미묘한 의미 오류를 모두 증명하지 못한다. 저장량보다 정확성을 우선한다.

### 3. Startup error visibility — 해소됨(2026-08-26 확인)

과거엔 lifespan이 broad `except Exception: pass`로 startup 실패를 숨길 수 있었으나, 현재는
schema 초기화 실패 시 `ready=False` + `error_log.record("startup_db", …)`, orphan approval·
resume·job 복구 블록도 각각 `error_log.record`로 남긴다(조용한 pass 없음). 조용한 먹통 위험 제거됨.

### 4. Auto Resume의 의미

현재 resume는 Python coroutine/checkpoint를 그대로 이어붙이는 것이 아니라 **persisted history/session state에서 안전한 새 run을 재구성**한다. independent durable worker/event-sourced continuation과는 다르다.

### 5. Host capabilities

Host PTY, host mode, screen/input/camera는 높은 권한이다. `FORGE_AUTH_TOKEN` 기본값은 비어 있으므로 remote 배포에서는 반드시 명시 설정 + Zero Trust/VPN 계층을 사용한다.

## 현재 KPI

우선순위:

1. `verified_task_success_rate`
2. `false_completion_rate`
3. `human_interventions_per_task`
4. `repair_success_rate`
5. `cost_per_verified_task`
6. `elapsed_per_verified_task`

실패를 정직하게 보고하는 것은 허용된다. 실패했는데 성공이라고 말하는 것이 가장 나쁘다.

## 다음 우선순위

### P0 — Dogfood reliability

- gate semantic coverage/false-negative를 실제 작업과 benchmark에서 수집.
- startup migration/resume exception visibility 개선.
- CompletionSummary/approval/steering에서 사용자가 불필요하게 개입하는 지점 측정.
- memory `saved/rejected` telemetry로 guard 품질 관찰.

### P1 — Provider independence

- 기존 DeepSeek behavior를 기준선으로 OpenAI-compatible adapter를 최소 구현.
- provider가 바뀌어도 AgentRuntime/verification/memory/skills는 바뀌지 않게 한다.
- 새 모델 승격은 verified success → cost/success → elapsed 순으로 평가.

### P2 — Persistent execution

- Scheduler의 Deferred/Condition semantics.
- API process와 독립적인 durable worker/queue가 실제로 필요한지 설계/PoC.
- restart/idempotency/run ownership을 더 명확하게 한다.

### P3 — Bounded workers

- fresh-context worker는 read-only/독립 task부터.
- shared-file mutation은 isolation/ownership 없이는 병렬화하지 않는다.
- verified throughput 개선이 없으면 도입하지 않는다.

### P4 — Tool/Execution optimization

Tool Script/RPC, Local/Docker/SSH ExecutionBackend는 현재 architecture 의무사항이 아니다. 측정된 round-trip/운영 문제가 생길 때 구현한다.

## Test snapshot

기준 SHA `32efec6`(2026-08-26): `SANDBOX_MODE=host pytest -q` **272 passed**(forge_test 격리 DB),
`ruff check .` 통과, `bench.py --self-test` 통과, frontend `npm test` 24/0 · `npm run build` OK.
수치는 코드 변경 시 재검증한다(자동화 전까지 hardcode된 값은 낡을 수 있음).
