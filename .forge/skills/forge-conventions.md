# FORGE 컨벤션

## 커밋·Git
- 커밋 메시지는 한국어. 제목 한 줄 + 본문(무엇을·왜).
- 커밋 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- push 전에 항상 최신 반영: `git fetch origin`, 뒤처졌으면 `git pull --rebase origin main` 후 push (병렬 커밋 환경).
- main에 바로 커밋·push한다(개인 프로젝트).

## 보고 형식
작업을 마치면 핵심 위주로 **요청사항 · 변경사항 · 작업 결과** 구조로 보고한다.

## 모델 정책 (품질 보장 + 비용 효율)
- 최우선 목표는 **verified success**다. 저렴하게 실행하는 것 자체가 목표가 아니다.
- 저비용 모델을 기본으로 사용하되 Harness의 실행·검증·수리·복구 프로세스로 결과 품질을 보장한다.
- Flash 사용률이나 `token/task` 감소 자체를 성공 지표로 삼지 않는다.
- 실패·불확실성이 증가하면 더 강한 모델로 bounded escalation한다.
- 모델 정책 변경은 benchmark의 `success_rate`를 우선한다. 성공률이 유지될 때 `cost_per_success`, elapsed, human intervention 순으로 비교한다.
- 비용을 줄이기 위해 verification을 약화하거나 실패율 상승을 허용하지 않는다.

## UI (모바일 PWA)
- 다크 웜 테마: 배경 `#262523` 계열, accent 코랄 `#d97757`. 임의 색 금지, 토큰 사용.
- 모바일 세로 최우선, safe-area 필수(`env(safe-area-inset-*)`).
- 어시스턴트 답변은 배경 위에 흐르고(버블 없음), 도구 활동만 카드. 유저는 코랄 버블.
