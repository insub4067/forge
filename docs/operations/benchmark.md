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

## 기준 작업

| 코드 | 유형 | 예시 프롬프트 |
|---|---|---|
| A | 단순 파일 수정 | "README에 실행 방법 한 줄 추가" |
| B | 단일 버그 수정 | "calc.py의 subtract가 덧셈을 한다 — 고쳐" |
| C | 여러 파일 리팩터링 | "store의 세션 조회를 공통 헬퍼로 묶어" |
| D | 테스트 실패 디버깅 | "test_review_loop 실패 원인 찾아 고쳐" |
| E | UI 수정 | "빈 화면 문구 문구 바꾸고 여백 조정" |
| F | 일반 질문 | "이 프로젝트 구조 요약해줘" (CHAT 경로) |

## 기록 표 (실행 후 채움)

| 작업 | 성공 | model | prompt | output | cache% | elapsed(s) | Pro | Debugger | $ |
|---|---|---|---|---|---|---|---|---|---|
| A |  |  |  |  |  |  |  |  |  |
| B |  |  |  |  |  |  |  |  |  |
| C |  |  |  |  |  |  |  |  |  |
| D |  |  |  |  |  |  |  |  |  |
| E |  |  |  |  |  |  |  |  |  |
| F |  |  |  |  |  |  |  |  |  |

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
