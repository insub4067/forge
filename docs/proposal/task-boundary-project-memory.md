# Task-Boundary Project Memory Extraction

> 상태: Proposal (2026-08-24)
> 상태 갱신(2026-08-24): M0 구현 + **evidence-bound hardening 완료**. 자유 서술 적립은
> 제거됐다 — candidate는 {fact, source, evidence} 구조로만 받고 `memory_guard`가 결정적으로
> 검증한다. 현재 구현은 `docs/status/work-status.md`의 "Project Memory — Evidence-Bound"가
> authoritative. M1(승인형)·M2(selective retrieval)는 미착수.
> 목표: 작업이 끝날 때 **검증된 프로젝트 지식**을 durable memory로 추출해, 다음 세션(특히
> "새 세션·같은 워크스페이스")이 프로젝트 구조·규약·빌드 방법·반복 문제를 다시 설명받지 않고
> 이어가게 한다. **long-term project memory ≠ long conversation context** 를 분리한다.

## 왜 (제품 헌법 §6)

FORGE의 North Star는 "매일 켜놓고 맡기는 상주 개발 에이전트"다. 그런데 지금은 작업 단위가
바뀌면(또는 fork-session으로 새 세션을 열면) 컨텍스트가 비어, 프로젝트 맥락(build 방법·coding
convention·이전 결정·자주 나는 문제)을 사용자가 다시 알려주거나 에이전트가 다시 탐색해야 한다.
마라톤 세션은 비용·드리프트를 유발하고(오늘 실측), 새 세션은 맥락을 잃는다. 이 둘의 간극을
"작업 경계에서 검증된 지식만 적립"으로 메운다.

## 현재 구현 (재사용 대상)

- `<workspace>/ROOM_MEMORY.md` — 방(워크스페이스) 메모리 파일. `_load_room_memory`가 읽어 매
  호출 시스템 프롬프트에 주입한다(`_system_for`). **읽기·주입은 이미 됨.**
- `GLOBAL_MEMORY.md` — 전역 메모리(동일 메커니즘).
- `_reflect` — run 종료 시 결정적 사실(반복 검증 실패)로 refinement 후보를 만든다(적용 안 함).
- Skills(Curated/Learned/Project) + `save_skill` — 반복 절차 적립.
- fork-session — 같은 워크스페이스로 새 세션(컨텍스트 리셋). ROOM_MEMORY는 자동 주입되므로
  적립만 되면 새 세션이 그대로 잇는다.

**간극**: 작업 성공 시 그 세션에서 얻은 durable 지식을 ROOM_MEMORY로 자동 적립하는 단계가 없다.
모델이 수동으로 write_file/save_skill 할 수는 있으나 체계적이지 않다.

## 설계 (bounded, 최소 변경)

### Phase M0 — 검증된 완료 시 memory 후보 추출
- 트리거: `finish("completed")` (검증 통과한 완료만 — 미검증/실패는 제외해 오염 방지).
- 입력(process-owned 사실만, 모델 self-report 아님): 사용자 goal, 통과한 acceptance gates,
  변경 파일 목록, 검증 명령/결과, 반복해서 유효했던 절차.
- utility 모델(flash)로 **1~3줄 durable 사실**을 뽑는다. 예: "빌드: `npm run build`(host)",
  "테스트: pytest, asyncio_mode=auto", "인증 세션은 Redis 필요 — 없으면 검증 unavailable".
- 대화·추론·일회성 해결은 제외(§6: memory ≠ conversation).

### Phase M1 — 안전한 적립
- 두 방식 중 택(구현 시 결정):
  - (a) **후보 방식**: refinement처럼 사용자 승인 후 ROOM_MEMORY 반영(신뢰성 우선, 헌법 §19).
  - (b) **자동+상한**: ROOM_MEMORY는 저위험(컨텍스트 힌트)이라 dedup+크기 상한(예 2KB) 하에
    자동 append. 사용자가 파일로 언제든 편집.
- **중복 방지**: 기존 ROOM_MEMORY와 의미 중복이면 추가 안 함.
- **크기 상한**: ROOM_MEMORY가 무한 성장하면 컨텍스트 비용이 된다 → 상한 초과 시 오래된/
  낮은가치 항목 축약(§7 context hygiene와 정합, 벤치로 성공률 회귀 없음 확인).

### Phase M2 — retrieval 정련 (후속)
- ROOM_MEMORY가 커지면 전량 주입 대신 작업 관련 항목만 selective retrieval(skills처럼).
- 지금은 파일이 작아 전량 주입으로 충분 — M2는 실측상 필요할 때만.

## Non-goals (하지 않을 것)

- 대화 히스토리를 영구 보존하지 않는다(그게 마라톤 세션의 비용 문제).
- 미검증/실패 결과를 memory로 적립하지 않는다(false knowledge 오염 금지).
- 새 저장 인프라·DB 마이그레이션을 만들지 않는다 — ROOM_MEMORY.md 파일 재사용.
- 자동 대규모 리팩토링/스코프 확대 없음(§18).

## 테스트 (결정적)

- completed(검증 통과) → memory 후보 추출됨 / verification_failed·completed_unverified → 추출 안 함.
- 추출 입력이 process-owned 사실뿐(모델 self-report 텍스트 배제).
- 중복 사실 재추출 시 ROOM_MEMORY 크기 안 늘어남(dedup).
- ROOM_MEMORY 상한 초과 시 상한 유지.
- 새 세션(fork) → ROOM_MEMORY 주입으로 이전 지식이 프롬프트에 존재.

## 판단

작지 않지만 과하지도 않은 중간 규모. 헌법 우선순위상 P1(§23). **completion·verification(P0)이 이미
탄탄해진 지금이 적기** — 검증된 지식만 적립하므로 신뢰성 기반이 선행돼야 했다. 구현 시 M0→M1(a)
(후보 방식)부터 시작해 신뢰성을 지키고, 자동화(M1b)·selective retrieval(M2)는 실측 후 결정.
