# FORGE 외부 리뷰 — 2026-08-26

> 감사 대상: `main` (얕은 클론, 최근 30커밋 기준)
> 범위: `backend/app/runtime`, `backend/app/sandbox`, `backend/app/orchestrator`, `rsi.py`, `rsi_run.py`, `bench_tasks.py`, `gate_eval.py`, `docs/`
> 확인 방식: 정적 읽기. 런타임 실행·telemetry 로그·실제 벤치 수치는 확인하지 않았다.
> 작성 주체: 외부 리뷰(Claude). **판단 권위는 코드에 있다** — 아래 내용이 현재 소스와 다르면 코드가 맞다.

## 요약 판정

핵심 설계는 옳은 방향으로 서 있다. 완료 권한을 모델에서 분리하고(`completion_policy.resolve_completion_verification`), gate의 `passed/failed`를 프로세스 전용으로 clamp하고(`_GATE_STATUS_CLAMP`), 검증 불가와 검증 실패를 구분한 것(`classify_gate`)은 이 종류의 하네스가 실패하는 지점을 정확히 겨냥한 선택이다.

그러나 **"검증된 완료"라는 주장은 아직 성립하지 않는다.** 프로세스가 소유하는 것은 *판정의 실행*이지 *판정 기준의 유효성*이 아니기 때문이다. 게이트의 명령과 기대 문자열을 모델이 직접 쓰고, 그 게이트가 실제로 무언가를 판별하는지 확인하는 절차가 없다. 여기에 검증 명령이 워크스페이스 쓰기 권한으로 실행된다는 점이 겹치면, 현재 `completed` 상태는 "모델이 스스로 낸 시험을 스스로 채점하지는 않았다"까지만 보증하고 "요구사항이 충족됐다"는 보증하지 못한다.

우선순위: **P0-A, P0-B를 먼저 닫아야 나머지 모든 지표(gate coverage, traceability, R0 성공률, RSI 승격)의 해석이 성립한다.** 지금 상태에서 벤치 수치를 올리는 작업은 측정 대상이 불확실한 상태에서의 최적화다.

---

## 확인된 강점

근거와 함께 남긴다. 아래 개선을 하다가 훼손하면 안 되는 불변식이다.

| 항목 | 근거 |
|---|---|
| 모델의 "완료" 선언이 완료 권위가 아님 | `completion_policy.resolve_completion_verification` — gate 없음 → `completed_unverified` |
| gate `passed/failed`는 프로세스만 설정 | `_GATE_STATUS_CLAMP` — 모델은 pending/working/blocked/abandoned/unavailable만 |
| 모델이 passed를 주장해도 재실행으로 덮어씀 | `verification.verify_gates` |
| 검증 불가와 검증 실패의 분리 | `classify_gate` — `unavailable` ≠ `failed` |
| 인프라 오류 오분류 방지가 양방향으로 설계됨 | `_gate_infra_error` — 파싱 오류는 traceback이 `<string>`/`<stdin>`일 때만 infra |
| 요구사항 단위 추적 | `traceability.compute_traceability` → `false_completion_candidate` |
| 못 잡는 실패 유형을 숨기지 않음 | `gate_eval.CASES` — `detectable=False`를 명시 (F6) |
| 벤치 checker 자체의 유효성 검증 | `bench_tasks` — `setup` 직후 `check==False`, `fix` 후 `check==True` |
| RSI가 자동 병합하지 않음 | `rsi_run` — worktree + 사람 승인 |

특히 마지막에서 두 번째 항목이 중요하다. **런타임 게이트에 지금 빠져 있는 것이 바로 이 패턴이다.**

---

## P0-A. 게이트의 유효성이 검증되지 않는다

**현상.** Developer가 `verification_method`와 `expected_result`를 모두 작성한다. `classify_gate`는 `exit 0 AND expected in output`이면 `passed`를 준다. 따라서 `echo hello` / expected `hello`는 통과한다 — 이건 추측이 아니라 `gate_eval.case_f5_valid_but_flagged`가 **정상 통과 사례로 정의해 둔 픽스처**다(`_gate(1, "로그인", "echo hello", "hello")`).

**왜 문제인가.** 시험 문제를 응시자가 낸다. 자기충족 게이트(대상 코드를 전혀 건드리지 않고도 통과하는 명령)와 진짜 게이트가 판정 체계상 구분되지 않는다. 모델이 악의적일 필요도 없다 — 실패를 줄이는 방향의 압력만으로 통과하기 쉬운 명령으로 수렴한다. `gate_semantic_coverage`는 게이트가 requirement에 *연결됐는지*만 세므로 이 수렴을 잡지 못한다.

**조치 — 변경 전 실행(pre-change probe).**

게이트 등록 시점에 각 `verification_method`를 **변경 이전 코드**에서 한 번 실행한다.

- 변경 전에도 `passed` → 그 게이트는 아무것도 판별하지 않는다 → `gate_validity="trivial"`로 표시하고 `requirements_verified` 집계에서 제외.
- 변경 전 `failed`, 변경 후 `passed` → 유효한 게이트.
- 변경 전 `unavailable` → 판정 보류(현행대로).

이건 `bench_tasks`의 `fix()` 패턴을 런타임으로 이식하는 것이다. 이미 프로젝트 안에 있는 아이디어이므로 새 개념을 들이지 않는다.

**구현 지점.** 워크스페이스 스냅샷은 이미 있다(`verification.verify_snapshot`). 변경 전 상태는 git 기반(`git stash` 또는 `git worktree add --detach HEAD`)으로 확보하는 편이 파일 스냅샷 복원보다 안전하다. 비용은 게이트당 `run_verify` 1회 추가.

**측정.** 도입 후 첫 지표는 "등록된 게이트 중 trivial 비율"이다. 이 숫자가 현재 `completed` 신뢰도의 상한을 그대로 말해 준다.

---

## P0-B. 검증 명령이 워크스페이스 쓰기 권한으로 실행된다

**현상.** `sandbox/executor.py`의 `run_verify()`는 docker 모드에서 워크스페이스를 읽기 전용이 아니라 쓰기 가능으로 마운트한다(`-v {workspace}:/workspace`, 주석: "bash(write=True)와 동일 권한"). `verify_cleanup()`은 검증이 **새로 만든** 파일만 지우고, 기존 파일의 수정은 되돌리지 않는다.

**왜 문제인가.** 게이트 명령이 검증 도중 소스를 수정할 수 있고, 그 수정이 남는다. 게이트 A의 명령이 게이트 B의 통과 조건을 만들어 놓는 경로가 열려 있으며, 판정 후 정리 단계에서도 흔적이 지워지지 않는다. P0-A와 결합하면 self-grading 방지 장치가 사실상 우회 가능해진다. 현재 이 경로를 막는 테스트는 확인되지 않았다.

**조치.**

1. 검증은 워크스페이스 **사본**에서 실행한다(가장 안전, 격리가 명확).
2. 사본이 비싸면 `:ro` 마운트 + 쓰기 가능한 별도 스크래치 경로. 단, 테스트 러너가 캐시/빌드 산출물을 쓰는 경우가 많으므로 사본 쪽이 실무적으로 덜 깨진다.
3. 최소 대응: 검증 전후 워크스페이스 해시를 비교하고, 검증 중 기존 파일이 바뀌면 그 게이트를 `unavailable`(사유: 검증이 대상을 변경함)로 강등.

3번은 하루면 들어가고 관측만으로도 실태를 알 수 있으므로, 1번을 준비하는 동안의 임시 조치로 쓸 만하다.

---

## P0-C. 운영 기본값이 host 모드 + 정규식 블랙리스트

**현상.**

- `docs/status/handoff-2026-08-23.md`에 따르면 실제 운영은 개인 Mac에서 `SANDBOX_MODE=host` + cloudflared 터널이다. 즉 docker 격리는 실사용 경로에 없다.
- host 모드에서 유일한 방벽은 `executor._DANGEROUS` 정규식 7패턴이다.
- `config.require_auth` 기본값은 `False`. fail-closed 장치(`auth.assert_startup_auth`)는 존재하지만 `FORGE_REQUIRE_AUTH=1`일 때만 동작한다.
- README의 Getting Started는 `--host 0.0.0.0` 바인딩을 안내한다.

**왜 문제인가.** 정규식 블랙리스트는 명령 문자열 표면만 본다. 변수 치환, `find ... -delete`, `python3 -c`를 통한 파일 조작 등 우회가 자명하고, 이 목록으로 host 셸을 방어한다는 전제는 성립하지 않는다. 여기에 auth 기본 꺼짐 + `0.0.0.0` 바인딩 안내가 겹치면, 기본 설정을 따른 사용자는 같은 네트워크에서 인증 없이 host bash·PTY·화면·카메라에 도달 가능한 상태가 된다. 문서에 경고가 있는 것과 기본값이 안전한 것은 다른 문제다.

**조치.**

1. `require_auth` 기본값을 `True`로 뒤집는다. 로컬 개발만 명시적으로 끄게 한다. 기본이 꺼진 보안은 없는 보안이다.
2. README 기동 예시를 `127.0.0.1` 바인딩으로 바꾸고, `0.0.0.0`은 인증 활성 상태에서만 안내한다.
3. host 모드의 방어를 **경로 화이트리스트**로 옮긴다 — 워크스페이스 밖 쓰기를 차단하는 쪽이 위험 명령 목록을 늘리는 쪽보다 방어 가능한 경계다. 블랙리스트는 보조로 남긴다.
4. 프롬프트 인젝션 경계를 문서화한다. 에이전트는 저장소 파일·테스트 출력·MCP 결과를 읽고, 같은 에이전트가 게이트를 등록한다. 즉 **데이터에서 온 문자열이 검증 기준을 바꿀 수 있는 경로**가 구조적으로 존재한다. 최소한 게이트 등록 입력의 출처를 분리하고, 신뢰 경계를 `docs/core`에 명시해야 한다.

---

## P1-D. RSI 승격 기준이 통계적으로 무의미하고, 벤치 오버핏이 목적함수다

**현상.** `rsi.promotion_gate`는 `success_rate` 후퇴가 없고 `cost_per_success`가 5% 이상 낮으면 PROMOTE한다. 표본은 R0 25태스크(`bench_tasks.TASKS`, 25개)다. 반복 실행 요구도, 신뢰구간도 판정에 들어가지 않는다.

**왜 문제인가.**

- 25개 이진 결과에서 1태스크는 4%p다. `min_sr_drop=0`은 노이즈에 대한 보호가 아니라 노이즈에 대한 과민 반응이며, 반대로 성공률이 우연히 유지된 후보는 통과한다. `bench_baseline.py`는 `--repeat 3`을 지원하는데 승격 판정은 단일 집계를 받는다.
- 더 근본적으로, 승격 조건이 "이 25개에서 성공률 유지 + 더 싸게"이므로 **최적화 방향 자체가 R0 특화**다. holdout이 없으면 벤치에만 맞는 변경이 계속 승격되고, RSI 루프에서 이 편향은 복리로 누적된다. `no-op reject`는 무변경 후보만 거를 뿐 벤치 특화 변경은 거르지 못한다.

**조치.**

1. `promotion_gate`가 반복 집계(repeat ≥ 3)를 요구하게 하고, 성공률 비교를 점추정이 아니라 Wilson 신뢰구간 하한으로 한다.
2. 태스크를 분리한다 — 승격 판정용(예: 20개)과 **RSI 판정에 절대 쓰지 않는 holdout**(예: 5개 + 신규 추가분). holdout 성공률이 후퇴하면 비용이 아무리 낮아도 REJECT.
3. 승격 리포트에 holdout 결과를 필수 항목으로 넣는다. 리포트에 없으면 사람이 승인 판단을 할 근거가 없다.

---

## P1-E. 벤치 측정 환경과 운영 환경이 다르다

`bench_baseline.py`의 실행 안내는 `SANDBOX_MODE=host`이고, `config`의 기본 실행 모드는 `docker`다. 두 모드는 네트워크(`--network none`), 메모리 512m, CPU 1, 마운트 권한이 전부 다르다. 서로 다른 실행 경계에서 잰 성공률은 이전되지 않으며, 특히 네트워크 접근이 필요한 태스크는 모드에 따라 결과가 뒤집힌다.

**조치.** 벤치를 두 모드에서 각각 돌려 차이를 수치로 남기거나, 운영 모드를 벤치 모드와 일치시킨다. 어느 쪽이든 `environment.json`의 sandbox 필드를 승격 판정의 비교 조건에 포함시켜, 모드가 다른 baseline/candidate 비교는 거부해야 한다.

---

## P1-F. Reviewer가 항상 Developer 이하이고, 리뷰 검출력은 측정되지 않는다

**현상.** `orchestrator/model_router.py` 주석에 따르면 planner/reviewer/triage는 비용 때문에 flash 고정이다. Developer는 flash-first에 pro 에스컬레이션이 있다. 즉 어려운 작업일수록 Developer는 강해지고 Reviewer는 그대로다 — 검토자가 생성자보다 약한 구조가 난이도에 비례해 심해진다.

`test_reviewer_capability.py`는 Reviewer의 **도구 격리**(read-only 강제)를 검증한다. 이건 잘 만들어진 테스트지만 **검출력 측정이 아니다.** Reviewer가 결함을 실제로 잡아내는 비율은 현재 어디에서도 재지 않는다.

**조치.** `gate_eval.py`의 F 시리즈와 같은 방식으로 결함 주입 세트(가칭 R 시리즈)를 만든다 — 알려진 결함이 심긴 diff를 Reviewer에 넣고 검출률과 오탐률을 잰다. 그 숫자를 보고 셋 중 하나를 택한다: 존치, Developer와 동급 티어로 승급, 또는 제거. **검출력이 낮은 리뷰 단계는 비용과 지연만 쓰면서 "리뷰를 거쳤다"는 잘못된 신뢰를 만든다** — 이건 리뷰가 없는 것보다 나쁘다.

---

## P2-G. `agent.py`가 2,628줄, `run()`이 484줄, `_run_role()`이 432줄

`completion_policy.py`와 `verification.py`를 순수 함수 모듈로 떼어낸 것은 좋은 선례다. 그 작업이 아직 절반이다. 현재 `run()` 안에 라우팅·실행·검증·마감이 함께 있어 P0-A/P0-B를 넣을 때 회귀 위험이 크다.

**조치.** 같은 방식으로 계속 쪼갠다. 우선순위는 `run()` → (routing / execution / verification orchestration / finalization) 4단으로 분리. 리팩터링 자체가 목적이 아니라, **P0 수정을 안전하게 넣기 위한 선행 작업**으로 본다.

---

## P2-H. 문서와 코드의 수치 불일치

README는 backend 테스트 116개 통과라고 적고 있으나, 저장소의 테스트 함수는 251개이고 `docs/status/reliability-report-2026-08-26.md`는 242 passed로 적혀 있다. `docs/README.md`의 Freshness Policy 5항(빠르게 변하는 수치는 근거 commit이 있을 때만)이 스스로 지켜지지 않고 있다.

**조치.** CI가 실제 수치를 생성해 주입하거나, README에서 숫자를 빼고 리포트 링크만 남긴다. 자동화되지 않은 수치는 반드시 낡는다.

---

## 실행 순서 제안

**1주차 — 판정의 신뢰성 복구 (여기까지 하기 전 벤치 최적화 금지)**

1. P0-B 임시 조치: 검증 전후 워크스페이스 해시 비교 → 변경 감지 시 `unavailable` 강등
2. P0-A: 변경 전 게이트 실행 + `gate_validity` 필드 + trivial 게이트 집계 제외
3. P0-C 1·2번: `require_auth` 기본값 반전, README 바인딩 수정

**2주차 — 측정의 신뢰성 복구**

4. P1-D: holdout 분리 + 반복 집계 + 신뢰구간 하한
5. P1-F: R 시리즈 결함 주입 세트로 Reviewer 검출력 측정 → 존치 여부 결정
6. P1-E: 벤치/운영 모드 일치 또는 양쪽 측정

**그 다음**

7. P0-B 본 조치(사본 기반 검증), P0-C 3·4번(경로 화이트리스트, 신뢰 경계 문서화)
8. P2-G 분해, P2-H 수치 자동화

`docs/status/work-status.md`의 Next Priorities에 있는 provider 일반화와 병렬 워커는 위 항목보다 뒤다. 판정이 신뢰되지 않는 상태에서 provider를 늘리면 비교 축만 늘고 결론은 나오지 않는다.

---

## 이 리뷰가 확인하지 못한 것

정직하게 남긴다. 아래는 판단 근거에서 제외했다.

- 실제 telemetry — `gate_coverage.py`가 읽는 `logs/events-*.jsonl`을 보지 못했다. 따라서 `generic_only_rate`, `gate_missing_rate`, `recovery_success_rate`의 **실측치를 모른다.** P0-A의 심각도는 이 숫자로 확정된다.
- R0 실제 실행 결과 — `bench-results/`의 산출물을 확인하지 않았다.
- 프론트엔드, 스케줄러, MCP 서버, 터미널/화면/카메라 경로.
- 런타임 프롬프트(`docs/agents/*.md`)의 내용.

우선 `gate_coverage.py`를 최근 로그에 돌려 실측치를 이 문서에 덧붙이는 것을 권한다. 그 숫자 없이는 P0-A가 "이론적 구멍"인지 "현재 진행 중인 오염"인지 구분되지 않는다.

---

## 대응 현황 (2026-08-26, 코드가 authority)

리뷰 후 착수 결과. 각 항목의 근거는 커밋·테스트다.

| 항목 | 상태 | 근거 |
|---|---|---|
| **P0-A** trivial 게이트 탐지 | ✅ | `verification.make_prechange_worktree` — HEAD 격리 워크트리에서 게이트를 먼저 실행, 변경 전에도 passed면 `unavailable` 강등. `test_gate_isolation` |
| **P0-B** 검증 격리(임시조치) | ✅ | 게이트 명령 전후 `_worktree_git_hash` 비교 → 검증이 소스 바꾸면 `unavailable`. 본체(사본 검증)는 후속 |
| **P0-C** bind/README | ✅(부분) | README·실행 서버 `127.0.0.1`. `require_auth` 기본 반전은 운영자(Cloudflare Access 앞단) 결정으로 False 유지. #3(경로 화이트리스트)·#4(신뢰경계 문서) 후속 |
| **P1-D** RSI 통계 유의성 | ✅ | `rsi.wilson_lower`·`HOLDOUT_CODES`·`min_samples`. `bench.aggregate`가 promotion/holdout 분리. `test_rsi_promotion` |
| **P1-E** 벤치/운영 모드 대조 | ✅ | `bench --json`에 `sandbox_mode` 기록, `promotion_gate`가 모드 다르면 REJECT. config 기본 docker vs 운영 host 일치는 배포 결정으로 별도 |
| **P1-F** Reviewer 검출력 harness | ✅ | `reviewer_eval.py`(R 시리즈) — `--self-test` 무료, `--run` LLM 실측. 실제 검출률 수치는 `--run` 후 존치/승급/제거 결정 |
| **P2-H** 문서 수치 | ✅ | README→리포트 링크, `work-status.md` 287 passed |

**후속(미착수)**: P0-A/B 본체(`gate_validity` telemetry 지표·사본 기반 검증), P0-C #3·4, P2-G(`run()` 분해).
**실측 대기**: `reviewer_eval.py --run`(검출률), `gate_coverage` trivial 비율(P0-A 도입 후 관측).
