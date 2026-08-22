# FORGE Agent Loop Design

## 목적

FORGE는 단일 LLM 호출 기반 챗봇이 아니라, DeepSeek API의 비용 효율성을 활용해 반복적인 문제 해결 루프를 수행하는 Agent Runtime이다.

## 기본 Loop

```
Goal
 ↓
Plan
 ↓
Execute Tool
 ↓
Observe Result
 ↓
Reflect
 ↓
Next Action
 ↓
Repeat
```

## State 관리

Agent는 매 반복마다 현재 상태를 유지한다.

```json
{
  "goal": "로그인 오류 수정",
  "plan": [],
  "current_step": 2,
  "files_changed": [],
  "errors": [],
  "attempts": 1
}
```

## 실행 단계

### 1. Planning

사용자 요구사항을 분석하고 작업 계획을 생성한다.

### 2. Tool Execution

필요한 Tool을 호출한다.

예:

- read_file
- grep
- edit_file
- bash
- test

### 3. Observation

Tool 결과를 분석한다.

예:

- 코드 발견
- 테스트 실패
- 빌드 오류
- 예상 결과 불일치

### 4. Reflection

현재 결과를 평가하고 다음 행동을 결정한다.

## 종료 조건

Loop는 다음 조건에서 종료한다.

- 목표 달성
- 테스트 통과
- 최대 Step 초과
- 비용 Budget 초과
- 사용자 중단

## 보호 장치

- 최대 반복 횟수 제한
- 동일 Tool 반복 감지
- API 비용 제한
- Tool 권한 정책
- Human Approval Gate

## 설계 의도

FORGE의 경쟁력은 가장 강한 모델을 사용하는 것이 아니라, 적절한 작업 단위로 분해하고 저비용 LLM 호출을 반복하여 결과 품질을 높이는 Agent Runtime에 있다.
