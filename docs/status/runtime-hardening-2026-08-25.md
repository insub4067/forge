# 런타임 안정화 작업 보고 (2026-08-25)

> 실전 성공률 검증·런타임 안정화 단계. 기능 추가가 아니라 회귀 기준선 확보, Gate 오판
> 측정, 대형 파일 1차 분리, 원격 fail-closed, Scheduler/Auto Resume 보장 명확화.

## 1. 확인한 최신 HEAD

- 브랜치: `main`, 작업 시작 HEAD: `6afac5c`, origin 동기화·클린.
- 최근 커밋 흐름: 디자인 폴리싱/PDF 뷰어 수정(2eef5f3→6afac5c) + Intent Interpreter 제안 문서.
- 이번 작업으로 추가된 커밋: `a2a40bd`(gate_eval) · `7e4e769`(completion_policy 분리) · `277569f`(fail-closed).

## 2. 기존 구조와 핵심 문제

- 백엔드: FastAPI + `AgentRuntime`(runtime/agent.py 단일 엔진) + PostgreSQL(store.py) + stdio MCP + scheduler.
- 프론트: Vue3 PWA(App.vue 단일 + style.css).
- Executor: DockerSandbox(`run`/`run_verify`), host/docker 모드.
- 검증 인프라: pytest 26파일(대부분 결정적), 표준 test_script_suites가 standalone을 subprocess로 실행.
- 핵심 문제(우선순위):
  1. 회귀 기준선이 매 세션 새로 측정돼야 함(문서화된 baseline 부재).
  2. Gate 완료 판정 정확도가 케이스별로 측정·리포트되지 않음.
  3. agent.py 2549줄 등 대형 파일에 다책임 결합.
  4. 인증 기본값 fail-open(토큰 미설정 시 무동작) → 외부 노출 시 위험.
  5. Scheduler/Auto Resume의 실제 보장 수준이 코드에만 있고 명시 문서 부재.

## 3. 변경한 파일

| 파일 | 종류 | 내용 |
|---|---|---|
| `backend/gate_eval.py` (신규) | feat | Gate 오판 평가 장치 |
| `backend/test_gate_eval.py` (신규) | test | false PASS/FAIL 0 + gap 인식 회귀 |
| `backend/app/runtime/completion_policy.py` (신규) | refactor | 완료/게이트 판정 정책 순수 함수 |
| `backend/app/runtime/agent.py` | refactor | 위 정의 제거 후 re-export(인터페이스 불변) |
| `backend/app/config.py` | feat | `require_auth` 추가 |
| `backend/app/auth.py` | feat | `assert_startup_auth`(fail-closed) |
| `backend/app/main.py` | feat | lifespan 최상단 fail-closed 게이트 |
| `backend/test_auth_boundary.py` | test | 원격모드 4조합 |
| `.env.example` | doc | `FORGE_REQUIRE_AUTH` |

## 4. 변경 이유

- **Gate 평가 장치**: FORGE 품질의 결정 변수는 에이전트 답변이 아니라 Gate의 완료 판정 정확도.
  8개 실패 유형별로 실제 판정 로직에 결정적 fixture를 넣어 false PASS/FAIL을 상시 측정.
- **completion_policy 분리**: agent.py 다책임 중 '무엇을 검증된 완료로 볼 것인가 + 모델 설정
  가능 상태'라는 순수 정책만 떼어내 독립 테스트·재사용. 순환 없음, 외부 동작 불변.
- **fail-closed**: 기존 fail-open은 로컬엔 편하나 원격엔 위험. 명시적 모드로 로컬/원격을 나눠
  원격에서 토큰 없으면 기동 거부.

## 5. 실행한 검증 명령과 실제 결과

```
cd backend && .venv/bin/python -m pytest -q      → 163 passed, 1 warning(Starlette httpx deprecation), ~26s
cd frontend && npm run build                     → 성공(청크 크기 경고만, 비치명)
cd backend && .venv/bin/python gate_eval.py      → Gate 판정 정확도 100%(detectable 6/6), false PASS 0
```

- lint/typecheck: **미구성**(프론트: eslint/tsconfig 없음, 백엔드: ruff/mypy 없음) → 이 항목은
  **미검증**으로 분류(성공 아님). pytest·build만 실검증.
- 경고 1건은 Starlette의 httpx deprecation(실패 아님).

## 6. Gate 평가 결과 (gate_eval)

- **판정 가능(detectable) 6유형 100% 정확, false PASS 0 / false FAIL 0**:
  - F1 테스트 실패 → gate `failed`(재실행 exit≠0)
  - F2 빌드 실패 → `failed`
  - F3 요구사항 일부 미검증 → `partial` → 완료판정 `completed_unverified`(완전 완료 아님)
  - F4 코드 변경 없이 설명만(gate 없음) → `completed_unverified`
  - F5 정상+통과조건 충족 → `completed`(false FAIL 아님)
  - F8 self-grading passed 주장 → clamp로 `working`, 방법 없으면 `unavailable`(evidence 필수)
- **F7 테스트 삭제/약화 — 감지·표면화 추가(`d10b3f7`)**: `change_guard.detect_test_weakening`이
  이번 변경의 `git diff --numstat`에서 테스트 파일 삭제·라인 순감소를 감지해 `test_weakening`
  경고로 표면화(비차단, verdict 미변경). gate_eval에서 gap → detectable로 승격, false PASS 0.
  verdict 차단은 정당한 리팩터 false-block 방지를 위해 별도 결정으로 분리.
- **남은 구조적 GAP 1유형**:
  - F6 무관한 파일 변경: gate는 verification_method 결과만 보고 변경 파일 범위를 대조하지 않음.
  - → 강화 후보: gate 검증에 변경 파일 범위 화이트리스트 대조 추가. test_gate_eval이 이 gap을
    상시 표시해 잊히지 않게 고정.

## 7. 호환성·마이그레이션

- **공개 API·DB 스키마·SSE 이벤트·프론트 동작 불변.** completion_policy 분리는 re-export로
  `A.<name>` 포함 인터페이스 유지. gate_eval은 순수 추가.
- **fail-closed 마이그레이션**: `require_auth` 기본 False → 기존 배포 무영향. 외부 노출 배포는
  `FORGE_REQUIRE_AUTH=1` + `FORGE_AUTH_TOKEN=<강한 토큰>` 설정 후 재시작하면 fail-closed 활성.
  토큰 없이 원격 모드로 켜면 명확한 오류로 기동 거부.

## 8. Scheduler / Auto Resume 실제 보장 수준 (#5 — 코드 기준 명세)

| 질문 | 실제 보장 | 근거 |
|---|---|---|
| API 재시작 후 예약 작업 보존 | **예** | `next_run_at`(DB, naive UTC)이 authoritative. 재시작 시 enabled 잡 복원. |
| 중복 실행 방지 | **예** | `claim_job`: 원자적 `UPDATE ... WHERE status!='running' SET running`, rowcount>0만 실행. |
| 여러 API 인스턴스에서 1회만 | **DB claim 한정 예 / 설계는 단일 인스턴스** | claim_job의 원자 UPDATE는 cross-instance 상호배제. 단 `runtime.is_running`은 in-memory(인스턴스별). 다중 인스턴스는 테스트·보장 대상 아님. |
| 실행 중 장애 상태 | **부분 갭** | 세션은 재시작 시 `take_interrupted_runs`가 running=False로 정리. **그러나 크래시로 죽으면 job.status가 'running'에 갇혀 재선점 안 됨**(job 상태는 startup 복구 없음). |
| Auto Resume가 중단 지점을 이어가나 | **정확 프레임 재개 아님 — 저장 history로 새 run 재구성** | `resume_run`은 스텝별 저장 history로 `runtime.run()`을 재실행. 완료된 스텝은 history에 있어 재수행 안 하지만, 실행 프레임 체크포인트 복원은 아니다. |
| 크래시 루프 방지 | **예** | 재개 시작 시 `final_status='resuming'`. 재개 중 또 죽으면 다음 기동에서 스킵(+잘못된 workspace 스킵, 20분 타임아웃). |

- **문서/UI 과대표현 없음**: durable worker/queue는 이미 architecture.md "Deliberately Not Yet"으로
  정직히 기술. 예약 탭 UI도 보장 문구 없음. 이번엔 과대표현 수정 불필요.
- **Durable worker 전환은 이번 범위 밖**(요청대로 미구현). 단계별 마이그레이션 계획:
  1. job 상태에 `claimed_at`·`heartbeat` 추가 → 크래시로 'running' 갇힌 job을 stale로 재선점.
  2. run_state event-sourcing 테이블(db-schema.md 후보)로 정확 프레임 체크포인트 재개 기반 마련.
  3. 독립 worker/queue 프로세스 분리(API와 실행 분리) → 그 후에야 다중 인스턴스 exactly-once 보장.

## 9. 남은 위험 / 다음 작업 우선순위

**남은 위험**
- lint/typecheck 부재 → 정적 회귀 감지 없음(미검증 항목).
- Gate F6/F7 구조적 gap(무관 파일·테스트 약화) → 잠재 false PASS.
- 크래시로 'running' 갇힌 예약 job 미복구.
- CORS `allow_origins=['*']` — fail-closed와 별개로 원격 모드에서 강화 필요.

**다음 작업 우선순위**
1. Gate 강화: F7 감지 완료(비차단 표면화, `d10b3f7`). 남은 F6(무관 파일 범위 대조) 추가 — gate_eval로 회귀 고정. (선택) test_weakening을 verdict 차단으로 승격할지 정책 결정.
2. 대형 파일 2차 분리 순서(책임 기준):
   - agent.py: **verification 계층**(`_verify`/`_verify_gates`/`_verify_integration`/`_gates_report`)을
     `runtime/verification.py`로(다음 후보 — 정책은 이미 분리됨, 검증 실행은 sandbox 의존이라 주입 필요).
     그다음 **context/prompt 빌더**(`_system_for`/`_select_skills`/`_compact`/`_project`),
     **memory 추출**(`_extract_project_memory`/`_parse_memory_candidates`).
   - routes.py(1133)·store.py(1086)는 도메인별 라우터/리포지토리 분할, App.vue(2017)·style.css(4318)는
     패널별 컴포넌트/CSS 모듈 분할 — 각각 회귀 스냅샷 확보 후.
3. 원격 모드 CORS 화이트리스트 + 보안 preflight를 기동 게이트와 연동.
4. 스케줄러 job heartbeat로 crash-stuck 복구(위 마이그레이션 1단계).
