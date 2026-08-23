# FORGE Skill 시스템

Skill은 단순 지식 메모가 아니라 **재사용 가능한 실행 절차**다. FORGE는 작업마다 모든 Skill을
프롬프트에 넣지 않는다 — 요청과 관련된 것만 골라 주입한다(selective retrieval).

## 3계층 구조

```
Curated Global   backend/app/curated_skills/*.md   (FORGE 번들·버전관리, 읽기 전용)
Learned Global   ~/.forge/skills/*.md              (save_skill scope=global로 축적, 모든 workspace 공유)
Project          <workspace>/.forge/skills/*.md    (해당 프로젝트 전용)
        ↓
   Skill Retriever (키워드 스코어 → 관련 상위 N개만)
        ↓
      Agent (system prompt의 dynamic tail)
```

| 계층 | 위치 | 용도 | 누가 쓰나 |
|---|---|---|---|
| **Curated** | 레포 `backend/app/curated_skills/` | 검증된 범용 방법론(최소구현·디버깅·검증) | 사람이 벤들, fresh install 즉시 사용 |
| **Learned** | `~/.forge/skills/` | 작업 중 성공한 범용 절차 | 에이전트가 `save_skill(scope="global")` |
| **Project** | `<workspace>/.forge/skills/` | 프로젝트 규약·빌드·구조 | 에이전트가 `save_skill()`(기본) |

Curated는 레포에 번들되어 버전관리되고 배포에 포함된다(홈이 비어도 즉시 사용 가능). Learned는
사용자 홈에 쌓여 여러 프로젝트가 공유한다. `~/.forge/skills`는 자체 git repo로 백업 가능하다.

## 우선순위

같은 이름이 여러 계층에 있으면 **Project > Learned > Curated**. 프로젝트의 명시적 규칙이
범용 규칙보다 우선한다. 점수가 같을 때도 project skill을 먼저 주입한다. 충돌 판단은 파일명(stem)
기준 — 복잡한 dependency graph는 두지 않는다.

## Selective Retrieval

전 계층 후보를 모아 요청 키워드와의 겹침으로 점수(제목 3, 본문 1)를 매기고, 상위
`MAX_ACTIVE_SKILLS`(3)개만 `SKILL_CHAR_BUDGET`(6000자) 안에서 주입한다. 관련 skill이 없으면
아무것도 넣지 않는다. Vector DB·embedding은 쓰지 않는다(측정된 병목 없음). Skill 본문은
프롬프트의 **dynamic tail**에만 들어가 prompt cache의 stable prefix를 깨지 않는다.

## save_skill

```
save_skill(name, content, scope="project")   # 기본 project
```

- **project**(기본): 프로젝트 특화 절차. 애매하면 여기.
- **global**: 특정 파일명·경로·도메인에 묶이지 않고 여러 코드베이스에서 재사용 가능한, 반복 가능하고 구체적인 성공 절차만. `~/.forge/skills`(learned)에 저장된다. curated에는 쓰지 않는다.

에이전트가 아무 성공이나 global로 올리지 못하게 기본을 project로 강제한다. 장기적으로
Project → (여러 작업 반복 성공 → 검증 → 사용자 승인) → Learned Global 승격 구조로 발전할 수 있으나,
현재는 자동 승격을 두지 않는다(설계가 막지는 않는다).

## Skill 품질 템플릿 (권장)

```
# 이름
## 언제 사용하는가
## 목표
## 절차
1. 2. 3.
## 검증
## 하지 말아야 할 것
```

강제는 아니지만 실행 가능성과 재사용성을 우선한다.

## 디렉터리 예시

```
backend/app/curated_skills/          # 번들 curated (레포)
├── minimal-implementation.md
├── systematic-debugging.md
└── verify-before-done.md

~/.forge/skills/                     # learned global (홈)
├── README.md                        # 인덱스(주입 제외)
└── <축적된 범용 skill>.md

<workspace>/.forge/skills/           # project
├── forge-conventions.md
└── forge-dev-workflow.md
```

`README.md`는 인덱스로 취급되어 skill로 주입되지 않는다.
