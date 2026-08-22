# Global + Workspace Skills 제안

> 상태: Proposal
> 목표: FORGE Skill을 프로젝트 전용 지식과 여러 workspace에서 재사용 가능한 전역 지식으로 명확히 분리한다.

## 1. 문제

현재 Skill은 workspace의 `.forge/skills/`를 중심으로 동작한다.

이 방식은 프로젝트별 지식을 격리하는 데는 좋지만, Desktop 같은 상위 디렉터리를 workspace로 선택하거나 다른 프로젝트로 이동하면 기존 Skill이 보이지 않는 것처럼 느껴질 수 있다.

반대로 Desktop 아래 모든 하위 프로젝트의 `.forge/skills/`를 재귀적으로 검색하는 방식은 피해야 한다.

```text
~/Desktop/
├─ forge/.forge/skills/
├─ trade-bot/.forge/skills/
└─ SwiftVue/.forge/skills/
```

이들을 전부 자동 합치면 현재 작업과 무관한 Skill이 선택되어 context 오염, 잘못된 절차 적용, token 증가를 일으킬 수 있다.

## 2. 제안 구조

Skill scope를 두 계층으로 분리한다.

```text
Global Skills
~/.forge/skills/
    ↓ 모든 workspace에서 사용 가능

Workspace Skills
<workspace>/.forge/skills/
    ↓ 해당 workspace에서만 사용
```

핵심 원칙:

> 재귀 탐색이 아니라 명시적인 Global + Workspace 2-tier 구조를 사용한다.

## 3. Scope 의미

### Workspace Skill

특정 repository/project에 종속된 지식이다.

예:

- FORGE frontend build 절차
- trade-bot 전략 검증 절차
- 특정 프로젝트 DB schema 주의사항
- repository-specific coding convention

저장 위치:

```text
<workspace>/.forge/skills/*.md
```

### Global Skill

프로젝트에 독립적으로 재사용 가능한 절차다.

예:

- FastAPI debugging
- Git recovery
- Vue build troubleshooting
- Python test debugging
- 일반적인 dependency investigation workflow

저장 위치:

```text
~/.forge/skills/*.md
```

## 4. 우선순위

동일 이름의 Skill이 두 scope에 존재하면 Workspace Skill을 우선한다.

```text
Workspace Skill
      >
Global Skill
```

이유는 프로젝트의 명시적인 local convention이 일반적인 전역 지식보다 높은 authority를 가져야 하기 때문이다.

예:

```text
~/.forge/skills/frontend-build.md
<workspace>/.forge/skills/frontend-build.md
```

현재 workspace에서는 두 번째 파일만 effective Skill로 사용한다.

## 5. Skill Selection

기존 selective loading 원칙을 유지한다.

```text
User Request
   ↓
Workspace Skills + Global Skills metadata
   ↓
중복/override 해결
   ↓
관련도 선택
   ↓
상위 N개만 context 삽입
```

Global Skill이 생겼다고 모든 Skill을 system prompt에 넣지 않는다.

현재 최대 개수/문자 budget 정책이 있다면 그대로 적용하고 benchmark를 통해 조정한다.

## 6. 저장 정책

`save_skill`은 scope를 명시할 수 있어야 한다.

개념적 인터페이스:

```json
{
  "name": "fastapi-debugging",
  "content": "...",
  "scope": "global"
}
```

또는:

```json
{
  "scope": "workspace"
}
```

기본값은 `workspace`를 권장한다.

Agent가 임의로 모든 성공 경험을 Global로 승격하면 전역 Skill이 빠르게 오염될 수 있기 때문이다.

## 7. Global 승격

초기에는 자동 승격하지 않는다.

권장 흐름:

```text
성공 경험
→ Workspace Skill 저장
→ 여러 프로젝트에서 반복적으로 유효함 확인
→ Global 승격 후보
→ 사용자 승인 또는 명시적 promotion
```

향후 benchmark/telemetry가 충분하면 자동 promotion proposal을 검토할 수 있다.

## 8. UI

Skills 화면에서 scope를 명확히 표시한다.

```text
Skills

프로젝트
├─ forge-dev-workflow
├─ frontend-build
└─ agent-debugging

전역
├─ git-recovery
├─ fastapi-debugging
└─ python-testing
```

각 Skill에는 최소 다음 정보를 표시한다.

- 이름
- scope
- source path
- 수정 시각
- 가능하면 최근 사용 여부

향후 사용량 telemetry가 있다면 성공률/사용 횟수를 추가할 수 있다.

## 9. Desktop Workspace UX

Desktop을 workspace로 선택했을 때 하위 프로젝트 Skill을 자동으로 수집하지 않는다.

예:

```text
Workspace = ~/Desktop
```

이 경우 effective Skill은:

```text
~/.forge/skills/*
~/Desktop/.forge/skills/*
```

뿐이다.

다음은 자동 검색하지 않는다.

```text
~/Desktop/forge/.forge/skills/*
~/Desktop/trade-bot/.forge/skills/*
```

사용자가 forge 프로젝트 Skill을 사용하려면 workspace를 forge로 선택하거나 필요한 Skill을 Global로 명시적으로 승격한다.

## 10. Context 효율

2-tier 구조는 Skill 수를 늘릴 수 있으므로 metadata scan과 content injection을 분리한다.

가능하면:

```text
name/path/description metadata
→ selection
→ 선택된 Skill content만 read
```

구조를 유지한다.

Skill 전체 본문을 매 요청마다 읽고 모델에 전달하지 않는다.

Vector DB는 현재 필요하지 않다.

Skill 수가 실제로 커져 filesystem scan이 병목으로 측정될 때만 SQLite FTS/index 등을 검토한다.

## 11. Security

Global Skill은 모든 workspace에 영향을 줄 수 있으므로 Workspace Skill보다 영향 범위가 크다.

따라서:

- Global Skill write는 별도 permission/approval 검토
- path traversal 방지
- `~/.forge/skills` 밖으로 쓰기 금지
- symlink escape 검토
- 외부 repository의 Skill을 자동 Global import하지 않음
- 웹에서 받은 instruction을 자동 Global Skill로 저장하지 않음

특히 prompt injection이 Global Skill persistence로 이어지는 경로를 차단해야 한다.

## 12. Telemetry

Skill 효과를 scope별로 측정한다.

예:

- selected skill names
- global/workspace scope
- selection count
- task success/failure
- Debugger activation
- model calls
- token usage
- cost per successful task

장기적으로 가치가 없는 Global Skill은 제거 또는 workspace scope로 축소할 수 있어야 한다.

## 13. API

기존 Skills API가 있다면 scope parameter를 확장한다.

개념적 예:

```text
GET /api/skills?scope=all
GET /api/skills?scope=global
GET /api/skills?scope=workspace
POST /api/skills
DELETE /api/skills/{scope}/{name}
```

정확한 endpoint는 현재 backend convention에 맞춘다.

API response에는 반드시 scope를 포함한다.

## 14. Migration

기존 `<workspace>/.forge/skills/`는 그대로 Workspace Skill로 취급한다.

따라서 기존 사용자 데이터 migration은 최소화할 수 있다.

새로 `~/.forge/skills/`를 지원하면 된다.

기존 Skill을 자동으로 Global로 이동시키지 않는다.

## 15. 단계

### G0 — Backend Scope

- global skill directory 정의
- workspace + global listing
- 동일 이름 override
- selection 통합
- path/security test

### G1 — save_skill

- scope argument
- workspace 기본값
- global write policy

### G2 — UI

- 프로젝트/전역 section
- scope badge
- 생성/삭제/수정 scope 처리

### G3 — Telemetry

- 어떤 scope의 Skill이 실제 성능을 개선하는지 측정

### G4 — Promotion

- Workspace → Global 수동 승격
- 충분한 데이터 이후 promotion suggestion 검토

## 16. 테스트

필수 테스트:

1. Global Skill이 여러 workspace에서 보인다.
2. Workspace Skill은 다른 workspace에서 보이지 않는다.
3. 동일 이름이면 Workspace가 Global을 override한다.
4. Desktop workspace가 하위 repository Skill을 재귀 수집하지 않는다.
5. save_skill 기본 scope가 workspace다.
6. Global 저장 path가 `~/.forge/skills`를 벗어나지 않는다.
7. symlink/path traversal로 scope boundary를 우회할 수 없다.
8. Skill selection budget이 기존과 동일하게 적용된다.
9. Global Skill 전체가 매 요청 context에 무조건 삽입되지 않는다.
10. 기존 `.forge/skills`가 migration 없이 계속 동작한다.

## 17. 하지 않을 것

초기에는 다음을 하지 않는다.

- Desktop 이하 Skill recursive discovery
- 모든 Skill global화
- Skill Vector DB
- 자동 Global promotion
- 외부 Skill marketplace
- repository에서 발견한 Skill 자동 설치
- Skill 본문 전체를 항상 system prompt에 삽입

## 18. 완료 기준

1. FORGE에 Global / Workspace 두 Skill scope가 존재한다.
2. UI에서 두 scope를 명확히 구분할 수 있다.
3. Global Skill은 모든 workspace에서 재사용 가능하다.
4. 프로젝트 전용 Skill은 해당 workspace에 격리된다.
5. 동일 이름 충돌 시 Workspace Skill이 우선한다.
6. Desktop workspace가 하위 프로젝트 Skill을 오염시키지 않는다.
7. 기존 selective loading/token budget 원칙을 유지한다.
8. Global Skill persistence가 별도 보안 경계를 가진다.

## 결론

FORGE Skill의 확장 방향은 하위 directory를 무차별 재귀 탐색하는 것이 아니다.

> **Global Skills + Workspace Skills + Workspace Override + Selective Loading**

구조가 적합하다.

이 구조는 프로젝트별 지식을 격리하면서도 여러 프로젝트에서 검증된 문제 해결 경험을 재사용할 수 있게 한다. 동시에 FORGE의 핵심 목표인 context 효율과 성공 작업당 비용 최적화를 유지할 수 있다.
