# 에이전트 모드 전환 (멀티/싱글) 결정 (2026-08-24)

> 올인원 Developer 단일 실행을 기본으로 유지하되, **필요한 작업에만 경량 멀티**
> (Planner → Developer → Reviewer)로 전환하는 기능을 추가했다.

## 왜 전환 기능이 필요한가

올인원 구조(2026-08-23 결정)는 비용·시간에서 크게 이겼다. 다만 단일 컨텍스트의 한계가 있다.

- 큰 다중모듈 작업은 설계·구현·검증이 한 컨텍스트에 섞여 품질이 흐트러진다.
- 자기검증은 독립 검증보다 눈이 약하다.
- 롱호라이즌 작업은 step budget·컨텍스트 압축에 걸린다.

그래서 "항상 멀티"가 아니라 **복잡 작업에만 멀티**를 쓰는 적응형으로 설계한다.
과거 멀티 파이프라인의 실패 원인(pro planner의 컨텍스트 재전송 73%, 역할 전환 churn)은
구조적으로 제거했다.

## 결정 주체: 사용자 명시 > FORGE 자동 (하이브리드)

세션 설정 `agent_mode`는 세 값을 갖는다(모델 티어와 동일한 UX 패턴).

| 값 | 동작 |
|---|---|
| `auto`(기본) | FORGE가 복잡도를 판정해 필요할 때만 멀티 |
| `multi` | 항상 Planner → Developer → Reviewer |
| `single` | 항상 올인원 Developer(변경 없음) |

- 사용자가 `multi`/`single`을 명시하면 자동 판정보다 우선한다.
- `auto`는 요청 특성(설계·리팩토링·아키텍처·대규모 키워드, 300자 이상 상세 요구,
  5회 이상의 멀티턴 작업)을 휴리스틱으로 판정한다.

## 멀티 흐름(경량 3역할, 전부 flash)

```
Planner(계획) → Developer(구현+승격 루프) → Reviewer(독립 검증) → [FAIL 시 Developer 1회 수정]
```

- **Planner** — 최근 메시지(최대 8)만 받고 읽기 전용 도구(read/list/grep)로 계획.
  완료 조건을 포함한 단계별 계획을 산출. 전체 컨텍스트를 재전송하지 않으므로
  과거 planner 비용 문제(73%)가 재발하지 않는다.
- **Developer** — Planner의 계획을 system에 주입받아 실행. 기존 승격 루프(막힘 시 pro)는
  그대로 동작하고 계획도 유지된다.
- **Reviewer** — git diff·테스트 실행으로 독립 검증. 마지막 줄에 `PASS` 또는 `FAIL: ...`.
  문제 시 Developer가 1회 수정(리뷰↔수정 왕복 churn 방지 — 루프 상한 1회).

## 비용·안전 장치

- 역할 전환은 Planner→Developer→Reviewer **단방향 1회**. 과거의 Reviewer↔Debugger 겉돌기 없음.
- Planner/Reviewer는 flash + 작은 step budget(10/12)으로 지연·비용을 억제.
- Planner 실패 시 계획 없이 올인원 Developer로 안전 폴백(작업 유실 없음).
- 모델 정책은 런타임 `get_policy`/`update_policy`로 planner/reviewer도 조회·변경 가능.

## 검증

- 결정적 오케스트레이션 테스트 8케이스 통과(`test_agent_mode_loop.py`):
  auto+simple→single / auto+complex→multi+plan 전달 / Reviewer FAIL→1회 재수정 /
  Reviewer PASS / 명시적 single 우선 / Planner 실패 폴백 / 멀티+승격 루프 / 멀티+최종 실패.
- 기존 회귀(`test_developer_loop.py`) 6케이스 통과 — 단일 경로 동작 불변.

## non-goal

- 여러 Developer의 병렬 워커(동시 구현)는 이번 범위 밖. 필요하면 후속으로
  Planner가 단계를 나누고 병렬 실행하는 구조로 확장한다.
