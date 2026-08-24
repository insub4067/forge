# GLOBAL_MEMORY

FORGE 에이전트가 모든 채팅방에서 공통으로 참고하는 전역 메모리.

> 보조 정보다. 현재 소스·설정과 충돌하면 반드시 현재 소스를 따른다.

## 프로젝트 규칙

- 변수명·함수명은 영어, 커밋 메시지는 한국어.
- 구현 전에 필요한 범위만 확인하고 변경은 최소화한다.
- 응답은 핵심만 짧게. 결론, 검증 결과, 다음 행동을 우선한다.
- 모델의 자기서술보다 process-owned test/gate/evidence를 우선한다.

## 반복 실패 기록

- **PWA 업데이트/캐시 stale 문제(해결됨)**: 수제 sw.js가 `/assets`를 cache-first로 캐싱해 새 배포가 화면에 반영되지 않는 문제가 있었다. 현재는 `vite-plugin-pwa`/Workbox 기반으로 관리한다. `frontend/dist`를 손으로 패치하지 말고 소스를 수정한 뒤 `npm run build` 또는 FORGE의 `build_frontend`를 사용한다.

## 기술 결정

- 백엔드: FastAPI + SQLAlchemy(async) + PostgreSQL.
- 프론트엔드: Vue 3 + Vite PWA.
- LLM provider: 현재 main은 **DeepSeek only**. Adapter 경계는 있으나 OpenRouter/Ling은 현재 구현이 아니다.
- 품질 authority: Generic Verification + Acceptance Gates + Integration Verification + process-owned CompletionSummary.
- Project Memory는 evidence/provenance validation을 통과한 사실만 저장하며, 현재 소스가 memory보다 우선한다.
