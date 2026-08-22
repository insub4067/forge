# FORGE 컨벤션

## 커밋·Git
- 커밋 메시지는 한국어. 제목 한 줄 + 본문(무엇을·왜).
- 커밋 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- push 전에 항상 최신 반영: `git fetch origin`, 뒤처졌으면 `git pull --rebase origin main` 후 push (병렬 커밋 환경).
- main에 바로 커밋·push한다(개인 프로젝트).

## 보고 형식
작업을 마치면 핵심 위주로 **요청사항 · 변경사항 · 작업 결과** 구조로 보고한다.

## 모델 정책 (비용 효율)
- 저비용 반복 철학: pro는 "정말 어려운 문제"에만.
- triage·chat·coder·reviewer·planner(기본)·debugger(기본) = flash.
- planner는 triage가 COMPLEX로 판정할 때만 pro 승격, debugger는 3회 실패 시 pro 승격.

## UI (모바일 PWA)
- 다크 웜 테마: 배경 `#262523` 계열, accent 코랄 `#d97757`. 임의 색 금지, 토큰 사용.
- 모바일 세로 최우선, safe-area 필수(`env(safe-area-inset-*)`).
- 어시스턴트 답변은 배경 위에 흐르고(버블 없음), 도구 활동만 카드. 유저는 코랄 버블.
