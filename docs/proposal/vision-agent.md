# Forge Vision Agent Proposal

## Overview

Forge는 단순한 코드 생성 Agent가 아니라 계획, 실행, 검증을 반복하는 Agentic Coding Platform을 목표로 한다.

`deepseek-v4-flash-vision-exp` 모델을 Vision Agent로 활용하여 AI가 생성한 결과물을 직접 보고 판단하는 검증 Loop를 구축한다.

## Goal

기존:

```
User Request
    ↓
AI Code Generation
```

개선:

```
User Request
    ↓
Planner
    ↓
Coder
    ↓
Build / Screenshot
    ↓
Vision Agent
    ↓
Review
    ↓
Fix Loop
```

## Vision Agent Responsibilities

### 1. UI Review

AI가 작성한 UI 결과물을 분석한다.

검증 항목:

- Layout
- Alignment
- Spacing
- Color Contrast
- Dark Mode
- Responsive Issue

Flow:

```
Coder Agent
    ↓
Screenshot Capture
    ↓
Vision Agent
    ↓
Issue Detection
    ↓
Task 생성
```

## 2. Screenshot Error Analysis

사용자가 전달한 오류 화면을 분석한다.

Input:

- Screenshot
- User Description
- Runtime Context

Output:

```json
{
  "type": "runtime_error",
  "severity": "high",
  "description": ""
}
```

## 3. Regression Detection

변경 전/후 화면을 비교하여 UI Regression을 탐지한다.

```
Before Screenshot
+
After Screenshot
+
Vision Agent
=
Regression Report
```

## 4. Design Understanding

사용자가 참고 이미지를 제공하면 구현 요구사항으로 변환한다.

Example:

```json
{
  "layout": "card based",
  "theme": "dark",
  "components": ["Navigation", "List", "Button"]
}
```

## Model Configuration

Model:

```
deepseek-v4-flash-vision-exp
```

Role:

```
Vision Perception Layer
```

## Agent Architecture

```
                 Orchestrator
                      |
        +-------------+-------------+
        |             |             |
    Planner       Coder        Vision Agent
  v4-pro        v4-flash    v4-flash-vision-exp

                      |
                 Reviewer
```

## Database Extension

Vision 분석 결과 저장:

```
vision_analysis

id
 task_id
 image_path
 analysis_result
 issues
 created_at
```

## Future Expansion

Vision Agent는 다음 영역으로 확장한다.

- Browser Agent
- Mobile Testing Agent
- Design System Validator
- Automated UI QA

## Conclusion

Vision Agent는 Forge에 "눈"을 추가한다.

Forge는 코드 작성뿐 아니라 결과물을 확인하고 스스로 개선하는 Agentic Coding System으로 발전한다.
