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

## Agent별 Model Policy

역할별로 비용 효율이 높은 모델과 추론 설정을 사용한다.

| Agent | 모델 | Thinking | Reasoning Effort |
|---|---|---|---|
| Planner | `deepseek-v4-pro` | enabled | high |
| Coder | `deepseek-v4-flash` | disabled | low |
| Reviewer | `deepseek-v4-flash` | enabled | medium |
| Debugger | `deepseek-v4-flash` → `deepseek-v4-pro` | disabled → enabled | low → high |

Debugger escalation 조건: `retry_count >= 3` 또는 `complexity == "high"`.

## Model Router

`backend/app/orchestrator/model_router.py` — Agent 타입·재시도 횟수·복잡도로 모델 선택.

- 정책은 런타임에 `get_policy()` / `update_policy()`로 조회·변경 가능
- 관리자 페이지에서 확인·변경 가능 (`/api/admin/model-policy`)
- 실행 시 사용한 모델·thinking·effort는 `agent_runs` 테이블에 기록

## DeepSeek Thinking 활용 전략

- reasoning(thinking)은 Planner·Reviewer처럼 깊은 추론이 필요한 단계에서만 사용
- Coder는 반복 실행이 많으므로 thinking을 꺼서 지연·비용 절감
- Debugger는 기본 flash로 시도하고, 재시도 3회 이상 또는 아키텍처 변경이 필요할 때만 pro로 격상

## Cost Optimization Strategy

강한 모델 하나를 쓰는 대신, 저비용 모델을 반복 실행하고 필요한 순간만 고성능 추론을 사용한다.

## 설계 의도

FORGE의 경쟁력은 가장 강한 모델을 사용하는 것이 아니라, 적절한 작업 단위로 분해하고 저비용 LLM 호출을 반복하여 결과 품질을 높이는 Agent Runtime에 있다.
