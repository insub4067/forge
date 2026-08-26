# Superpowers 프로세스 도입 — 짓기 전에 계획·생각

> 설계 문서(brainstorming 산출). 작성 2026-08-26. 상태: proposal.

## 목적

FORGE 에이전트가 요청을 바로 코딩으로 옮기지 않고 **짓기 전에 계획·생각**하게 한다. Superpowers(Claude Code 방법론)의 핵심 규율을 FORGE 프로세스에 이식하되, FORGE의 자율성(폰에서 던지면 알아서 완주)을 깨지 않는다 — 대화형 브레인스토밍을 그대로 넣지 않는다.

## 현재 상태 매핑 (중복 도입 방지)

| FORGE 지점 | Superpowers 패턴 | 상태 |
|---|---|---|
| Planner (`docs/agents/planner.md`) | brainstorming: 짓기 전 사고 | **net-new — 이 설계의 핵심** |
| Reviewer (`docs/agents/reviewer.md`) | code-review: 적대적·회의적 검증 | **보강 — 작은 net-new** |
| Developer | minimal-implementation(YAGNI) | 이미 curated 스킬 |
| Debugger | systematic-debugging | 이미 curated 스킬 |
| 검증 | verify-before-done | 이미 스킬 + 게이트 |
| Developer | TDD(테스트 먼저) | **범위 밖** — FORGE 게이트 검증 철학과 충돌·중복 |

결론: "프로세스 전반 도입"의 대부분은 이미 흡수됨. 실제 net-new는 Planner·Reviewer 2곳.

## 설계

두 층으로 둔다 — **글로벌 스킬(공유·확장)** + **역할 프롬프트(항상 적용 베이스라인)**.

### ① 글로벌 스킬 파일 — `~/.forge/skills/` (learned tier)

모든 FORGE 워크스페이스가 selective retrieval로 공유한다. 레포와 무관하게 사용자 홈에 산다.

- **`plan-before-build.md`** — 짓기 전 사고. 절차: (1) 가정을 드러낸다(모호하면 무엇을 가정하는지 계획에 명시 — 자율 실행이라 되묻지 않되 가정은 보이게), (2) 해법 공간이 넓으면 2~3개 접근을 떠올려 근거와 함께 하나 택함, (3) 범위를 깎는다(YAGNI), (4) 큰 요청은 순서 있는 하위작업 + 각 완료조건으로 분해. 한글 트리거 용어(계획·구현·만들·설계·기능·리팩터)를 본문에 넣어 실질 작업에 매칭되게 한다.
- **`adversarial-review.md`** — 적대적 검증. 통과를 전제하지 말고 깨뜨리려 시도한다(빈 입력·경계값·되돌린 케이스). 반증에 실패했을 때만 PASS.

### ② 역할 프롬프트 보강 — 항상 적용 베이스라인

글로벌 스킬은 키워드 선택식이라 안 뜰 때가 있다. 프롬프트 인라인이 최소 규율을 보장한다(스킬은 복잡한 작업에 풀버전을 얹음 — 중복이 아니라 베이스라인+확장).

- **`planner.md`**: "## 계획 전" 짧은 절 — 가정·접근·YAGNI·분해를 한 줄씩.
- **`reviewer.md`**: 한 줄 — "통과를 전제하지 말고 깨뜨리려 시도, 반증 실패 시에만 PASS."

## 검증

- `iter_skills`가 learned tier(`~/.forge/skills`)를 병합 대상에 포함하는지 확인(코드상 포함됨) → 새 스킬이 planner/reviewer에 실제 주입되는지 확인.
- 프롬프트 로딩 관련 테스트 통과(`_load_role`·`_select_skills`).
- bench 회귀: verified_success 유지, **false_completion 0 유지**(계획 규율이 완료 판정을 왜곡하지 않음).

## 범위 밖

- TDD(테스트 먼저): FORGE는 게이트 기반 검증이 검증 철학이라 별도 TDD는 충돌·중복.
- 대화형 브레인스토밍(사용자에게 한 번에 한 질문): FORGE 자율 UX를 깬다.
- Developer/Debugger 스킬 신규 추가: 이미 흡수됨.
