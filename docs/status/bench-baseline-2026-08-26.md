# 실측 벤치 baseline (2026-08-26)

> 목적: verified_success_rate·false_completion_rate·cost_per_verified_task의 기준선.
> 변경 전/후 비교와 Task IR ON 판단의 근거. 측정 코드는 `backend/bench.py`(25 task,
> deterministic checker), 실행: `python bench.py --run --repeat 1 --json <path>`.

## 조건
- main HEAD = `59f54ca`(requirement traceability + gate↔requirement 연결 + 실행 장부까지 반영).
- `TASK_IR_ENABLED` = **off**. 이 baseline은 traceability 강등 로직의 영향을 받지 않는다
  (강등은 Task IR ON일 때만 작동). 그래서 강등 변경과 무관한 깨끗한 기준선이다.
- tier=auto, repeat=1, 25 task 전수. 총비용 $0.14765.

## 신뢰성 핵심 지표
| 지표 | 값 |
|---|---|
| verified_success_rate | 0.92 (23/25) |
| false_completion_rate | 0.04 (1건 — W) — 완료 주장했으나 checker 실패(최악) |
| false_failure_rate | 0.04 (1건 — 실제로 됐는데 verification_failed로 과차단) |
| cost_per_verified_task | $0.00642 |
| total_cost | $0.14765 · cost_per_task $0.00591 |
| elapsed avg/p50/p95 | 26.9 / 22.6 / 53.6s |
| tool_calls/task | 8.08 · pro 승격 0 · 개입 0 · repair 0 |
| tokens prompt/completion | 1,308,533 / 37,507 · cache hit/miss 1,229,824 / 75,206 |

상태 분해: `completed=0 · completed_unverified=24 · verification_failed=1 · context_blocked=0`.

## 주목할 발견 — completed=0
25개 중 완전 검증(`completed`)에 도달한 task가 하나도 없다. gate 복구가 돌아도 passed gate가
만들어지지 않아 전부 generic verification만으로 `completed_unverified`에 안착했다.
false_completion 1건(W, "long-running 상태 영속화" COMPLEX)이 여기서 새어나갔다 — gate가
있었으면 걸렀을 것이다. Acceptance Gate 경로가 벤치에서 실효 검증을 만들지 못한다는 신호다.

## task별(성공/비용/p50s)
A $0.00262 14.2 · B $0.00349 18.6 · B2 $0.00395 17.0 · C $0.00870 28.1 · D $0.00687 28.7 ·
E $0.00761 32.9 · F $0.01155 45.5 · G $0.00579 22.6 · H $0.00284 19.8 · I $0.00248 16.2 ·
J $0.00509 19.3 · K $0.00178 8.9 · L $0.00401 11.1 · M $0.00237 20.9 · N $0.00699 28.8 ·
O $0.00424 19.4 · P $0.00394 18.9 · Q $0.01478 56.5 · R $0.00506 23.5 · S $0.00673 41.5 ·
T $0.00321 21.0 · U $0.01184 53.6 · V $0.00551 25.4 · **W 0/1(실패)** 50.8 · X $0.00578 30.3

## Task IR ON 재벤치 (같은 25 task, `TASK_IR_ENABLED=1`, 벤치 프로세스에만 적용)
| 지표 | baseline(off) | Task IR ON | 변화 |
|---|---|---|---|
| verified_success_rate | 0.92 (23/25) | **1.0 (25/25)** | +0.08 |
| false_completion_rate | 0.04 (W) | **0.0** | −0.04 (최악 실패 제거) |
| false_failure_rate | 0.04 | 0.0 | −0.04 |
| completed(완전검증) | 0 | **3** | +3 |
| cost_per_verified_task | $0.00642 | $0.00937 | **+46%** |
| total_cost | $0.14765 | $0.23412 | +58% |
| tokens prompt/completion | 1.31M / 37.5K | 1.83M / 75.0K | interpreter 호출 + 요구사항 프롬프트 |

바뀐 task: **W(long-running 상태 영속화)만 0→1로 개선**. 나머지 24개는 동일하게 성공.
악화 task 0건. `completed`가 0→3으로 처음 생겼다 — 요구사항 id를 gate 작성 role에 준
덕에 gate가 requirement로 추적돼 완전 검증 완료가 실제로 나왔다(강등 변경의 의도대로 작동:
추적이 되면 강등하지 않고, 오히려 gate 등록을 유도해 verified 완료가 늘었다).

**판단**: rollback 게이트("성공률이 baseline보다 낮으면 탈락") 통과 — 떨어지긴커녕 올랐다.
다만 **task당 1회(n=1)라 통계적으로 견고하지 않다** — 0.92→1.0은 W 한 건 차이로,
run-to-run 변동일 수 있다. 방향은 "해치지 않고 개선", 대가는 verified당 비용 +46%.
사용자 북극성이 신뢰성 우선·비용 후순위이므로 켤 근거는 있으나, 기본값을 뒤집기 전에
`--repeat 3`로 재확인하는 게 안전하다. `TASK_IR_ENABLED`는 아직 off(config·서버 불변).

## 다음 비교 대상
- Task IR ON `--repeat 3` — n=1 노이즈 제거 후 개선이 유지되는지.
- reasoning/write-folding variant — 최적화 ON이 성공률을 깎지 않는지.
