# FORGE 성능 benchmark

목적: FORGE 변경 전/후의 **cost per successfully completed task**를 데이터로 비교한다.
"느낌"이 아니라 계측값으로 판단하기 위한 기준 작업 모음.

## 측정 방법

각 작업을 새 세션에서 1회 실행하고, 완료 후 세션 효율 계측을 기록한다.

- API: `GET /api/rooms/{session_id}/metrics`
- UI: 메뉴 → 세션 사용량 → "효율 계측"

기록 항목(작업당):

| 항목 | 출처 |
|---|---|
| 성공 여부 | `final_status == "completed"` |
| model 호출 | `total_model_calls` |
| prompt tokens | `prompt_tokens` |
| output tokens | `completion_tokens` |
| cache 적중률 | `cache_hit_ratio` |
| elapsed | `elapsed_ms`(role 합) |
| Pro 승격 | `pro_calls > 0` |
| Debugger 발동 | `debugger_calls > 0` |
| 추정 비용 | `estimated_cost` (config `MODEL_PRICING` 기준) |

전체 추세: `GET /api/metrics/summary` — success_rate, avg_tokens_per_success,
review_first_pass_rate, pro_escalation_rate, debugger_activation_rate, 병목 rule.

## R0 자동 하네스 (`backend/bench.py`)

수동 표 대신 **격리 fixture + 결정적 checker**로 자동 측정한다. task는
`backend/bench_tasks.py`에 21개(카테고리 21종, COMPLEX 5). 각 task는
setup(fixture) → agent 실행 → check(테스트 실행·파일 내용·grep) → 집계 구조다.
LLM에게 "잘했는가"를 묻지 않는다(결정적 판정만).

```
python bench.py --self-test          # task checker 전수 + 집계 검증(무비용)
python bench.py --run --repeat 3     # 실제 실행(API 비용)
python bench.py --run --complex      # COMPLEX만(planner 실험)
python bench.py --run --task C,D     # 특정 task만
```

**품질 보증**: `test_bench_quality.py`가 정답 노출·카테고리 다양성·trivial 비중·중복·
상태 오염을 검사한다. bench self-test는 모든 checker가 미수정 fixture에서 False(false
positive 없음), 정답 적용 시 True(과도하게 엄격하지 않음)임을 전수 확인한다. stale
`__pycache__`는 채점 전 제거해 오판을 막는다.

### 실험 플래그 (env, 기본 off — 라이브 무변화)

| 플래그 | 효과 | 용도 |
|---|---|---|
| `FORGE_PLANNER_FLASH=1` | COMPLEX planner를 flash로 | 모델 비용 실험 |
| `FORGE_PLANNER_OFF=1` | COMPLEX에서 planner 생략 | planner 필요성 실험 |
| `FORGE_SKILLS_OFF=1` | skill 주입 비활성 | skill 효과 실험 |

동일 조건에서 Pro/Flash/No-Planner, skills on/off를 A/B로 비교한다. **가장 중요한 gate는
success_rate** — 비용이 낮아도 성공률이 의미 있게 하락하면 default를 바꾸지 않는다.

## 해석 지침

- **F(질문)가 AGENT로 라우팅되면** triage 정확도 문제 — CHAT이어야 저렴하다.
- **B/E에서 Debugger가 자주 뜨면** Coder 첫 통과율이 낮다 — review_first_pass_rate 확인.
- **Pro 승격이 잦으면** 난이도 판정이 과하거나 flash로 충분한 작업을 pro로 돌린 것.
- **cache% < 30%** 면 stable prefix가 요청마다 깨지는지 점검.

## 알려진 스케일 한계 (추측 최적화 금지)

`_select_skills`는 요청마다 모든 `.forge/skills/*.md` 본문을 읽어 keyword score를
계산한다. 현재 skill 수(<10)에서는 무시할 수 있다.

- skill 100개: 매 요청 파일 100개 read + 스코어링 — 수십 ms 수준, 아직 문제 아님.
- skill 1000개: 파일 I/O가 요청 지연에 드러날 수 있음.

**실제 profiling에서 병목이 확인될 때** metadata index 또는 SQLite FTS5를 도입한다.
그 전까지는 도입하지 않는다(측정 근거 없는 최적화 금지).
