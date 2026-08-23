# Curated Skill Index

FORGE에 번들되는 범용 Skill의 인덱스다. 이 파일 자체는 Skill로 주입되지 않는다.

> 현재 Runtime은 모든 Skill 본문을 로컬에서 읽어 keyword score를 계산하지만, LLM prompt에는 관련 상위 최대 3개·총 6000자만 삽입한다. 따라서 이 인덱스는 우선 사람과 향후 metadata-only retrieval을 위한 기준이다. Skill 수가 실제로 늘어 filesystem scan이 병목으로 측정될 때 이 인덱스를 runtime metadata source로 승격한다.

| Skill | 목적 | 대표 상황/키워드 |
|---|---|---|
| `minimal-implementation` | 과잉 구현을 막고 동작하는 최소 변경을 선택 | feature, refactor, YAGNI, dependency, helper reuse |
| `systematic-debugging` | 추측 패치 대신 재현→원인→최소수정→증명 | bug, failure, traceback, test fail, root cause |
| `verify-before-done` | 모델 주장 대신 실행 증거로 완료 판정 | verify, test, build, checker, completion |
| `change-impact-analysis` | 수정 전 호출부·계약·테스트 영향 범위를 확인 | API change, signature, schema, caller, dependency, regression |

## Scope

Curated Skill은 모든 workspace에서 사용 가능한 global scope다.

충돌 시 우선순위:

```text
Project > Learned > Curated
```

프로젝트나 사용자가 같은 이름의 Skill을 명시적으로 정의하면 Curated 기본값을 override한다.

## Retrieval 원칙

목표 구조는 다음과 같다.

```text
metadata/index
→ 요청과 관련된 후보 선택
→ 선택된 Skill 본문만 로드
→ 최대 N개 / 문자 budget 내 prompt 주입
```

단, 현재 Skill 수에서는 전체 로컬 파일 scan 비용이 미미하다. 실측 병목 없이 복잡한 인덱싱 계층이나 Vector DB를 추가하지 않는다.
