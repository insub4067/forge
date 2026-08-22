# FORGE 개선 계획

> 2026-08-22, 실측 기반 전체 검토.
> **핵심가치: 클로드급 성능을 저렴하게 — 최고급 하네스 + 스킬로. 작업은 끊기지 않고, 결과는 믿고 맡길 수 있어야 한다.**

## 현재 위치 (실측)

RSI 세션 실측: model 호출 159회 · tool 120회 · cache 적중 91.6% · 비용 $1.03 ·
**최종 status = review_limit (성공 아님)**. 중복 응답 7종(최대 x6)이 히스토리 오염.

구조(오케스트레이션·압축·회복·계측·선택 스킬)는 상위권. 그러나 **"끝까지 스스로
완수하고 결과를 신뢰"라는 기준에선 아직 실패**한다. 아래는 그 격차의 원인과 순서.

---

## P0 — 신뢰를 깨는 결함 (이것부터)

### 1. 중복 응답 저장 버그
같은 assistant 응답이 4~6회 히스토리에 저장된다(실측 7종).
- **피해**: 히스토리 오염 → 모든 후속 호출의 컨텍스트 낭비(비용↑) + 대화 UI 신뢰 훼손.
- **원인 후보**: reviewer 루프 재진입 시 동일 출력 재-append / 스티어링 주입 후 재실행 경로 /
  save_history(delete+reinsert)와 진행 중 run의 경합.
- **조치**: eventlog로 저장 시점 추적 → 원인 확정 → 저장 경로를 단일화(append-only가 이상적).
  회귀 테스트 필수.

### 2. 에이전트가 자기 검증을 못 한다 (review_limit의 근본 원인)
샌드박스에 node/pytest가 없어 프론트 빌드·백엔드 테스트를 못 돌린다.
- **피해**: Reviewer가 "검증 못 함" → 태스크 미완 → review_limit. **끝까지 못 가는 구조적 이유.**
  dist 손패치 같은 잘못된 우회를 학습(실제 발생).
- **조치**(택1, 권장 순):
  a. 샌드박스 이미지에 node+npm+pytest 추가(격리 유지, 네트워크는 계속 차단).
  b. `SANDBOX_MODE=host` 상시화(개인 환경 신뢰 전제. 이미 옵트인 구현됨).
- **판정 기준**: RSI급 작업에서 review_first_pass_rate 상승, review_limit 소멸.

### 3. 서버 재시작 = 작업 사망 (무중단의 최대 구멍)
현재는 reconcile(감지+안내)뿐, 이어서 실행하는 durable resume이 없다.
- **조치**: 단계적으로.
  1) run 상태(role·step·all_messages 스냅샷)를 주기 체크포인트로 DB에 저장.
  2) 재시작 시 마지막 체크포인트에서 재개(planner부터가 아니라 중단 지점부터).
  3) 이벤트 replay로 모바일 재접속 시 중간 과정 복원(이미 JSONL 로그 있음 — 소비만 구현).
- 배포(재시작)마다 작업이 죽는 지금 구조는 자기개선(RSI)과 양립 불가.

### 4. 승인 대기 = 작업 정지
600초 타임아웃은 "무한 매달림 방지"지 해결이 아니다. 승인 거부로 진행하면 태스크는 실패한다.
- **조치**: Web Push(작업 완료·승인 대기 알림)를 붙여 대기 시간을 분 단위로.
  (VAPID 키·pywebpush 준비됨, trade-bot push-sw.js 패턴 참고 가능.)

---

## P1 — 비용/성능 (클로드급을 싸게)

### 5. Planner 폭주 억제
실측: pro+high planner가 23 model call·1.4M prompt tokens·5.5분(1 role).
- planner 스텝 상한 분리(MAX_STEPS 30 공유 → planner는 8~10).
- planner는 탐색 최소화(계획만), 탐색은 coder로 이양 — 프롬프트+상한 동시 적용.
- 측정 후 pro+high → pro+medium 검토(품질 비교는 benchmark.md A~F로).

### 6. Tool Script/RPC 모드
model 호출 159회의 대부분이 "탐색 1회 = 왕복 1회".
- 읽기 전용 다중 명령을 한 번에 묶는 배치 도구(read_batch 또는 제한된 스크립트).
- 이미 read_file 범위 지원 추가됨 — 다음은 "여러 파일·여러 범위 한 방".
- **기대**: 왕복 수 ~40% 감소(= 시간·비용 동시 절감). 병목 rule이 이미 이를 지목.

### 7. 스티어링마다 triage 재실행 제거
한 세션에서 triage 5회 실측. 실행 중 주입/추가 메시지는 분류가 필요 없다.
- 진행 중 세션의 후속 메시지는 triage 생략(주입 경로는 이미 생략됨 — 새 run 경로 점검).

### 8. Vision 조건부 실행
이미지가 있으면 무조건 vision 선행 → 단순 첨부에도 비용.
- triage가 "이미지 분석 필요"까지 판정하거나, vision 결과 캐시(같은 이미지 재분석 금지).

---

## P2 — 하네스/스킬 고도화 (지속 개선 루프)

### 9. 스킬 축적 루프 실동작화
save_skill이 있지만 실제 축적은 수동에 가깝다. GLOBAL_MEMORY 반복 실패 기록도 수동.
- run 종료 시(성공/실패 모두) "이번 run에서 배운 것" 1회 자기평가 → skill/메모리 제안.
- review_limit·실패 세션은 원인을 GLOBAL_MEMORY '반복 실패'에 자동 기록(승인 게이트 유지).
- **이게 돼야 "쓸수록 좋아지는" 하네스가 된다.**

### 10. 평가 루프(benchmark) 정례화
benchmark.md A~F를 실제로 돌려 수치 기록 → 변경 전/후 비교가 습관이 되게.
- 목표 지표: success_rate, cost_per_success, review_first_pass_rate.
- "느낌"으로 모델·프롬프트를 바꾸지 않는다.

### 11. 역할 프롬프트 정비
- orchestrator.md는 어떤 role도 읽지 않는 죽은 문서 — 삭제하거나 README로 이동.
- vision·triage 프롬프트는 코드 인라인 — docs/agents로 통합(관리 일원화).
- 각 role.md에 "검증 명령 예시"(npm build, pytest 경로) 명시 → 자기검증 유도.

### 12. 세션 간 지식 공유
방이 달라지면 이전 방의 해결책을 모른다.
- GLOBAL_MEMORY 활용을 프롬프트에서 강제(이미 로드는 됨 — 기록이 안 쌓이는 게 문제, #9와 연동).

---

## 하지 않는다 (반가치)

- vector DB / 외부 analytics / 거대 프레임워크 — 측정된 병목 없이는 금지.
- 멀티 프로바이더 추상화 확대 — DeepSeek 하나로 충분(Adapter는 이미 있음).
- UI 대공사 — 단순 UI는 완료 선언(사용자 확인).

## 실행 순서 제안

1. **P0-1 중복 저장** (신뢰 즉효, 비용도 절감)
2. **P0-2 샌드박스 검증 능력** (review_limit 소멸 = success_rate 직행)
3. **P1-5·6 planner 상한 + tool 배치** (비용 반감 후보)
4. **P0-3 durable resume** (무중단의 완성, 가장 큰 공사)
5. **P0-4 Web Push** (대기 단축)
6. P1-7·8 → P2 순.

각 단계 후 benchmark로 전/후 수치 비교. 판단 기준은 언제나
**cost per successfully completed task**.
