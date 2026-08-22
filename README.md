# FORGE

셀프호스팅 **Agent Runtime 기반 코딩 AI 플랫폼**. 자연어 요구사항을 받아 계획 → 실행 → 검토 → 수정 → 재검증을 반복하며, Mac에서 장시간 실행하고 모바일 PWA로 원격 제어한다.

FORGE의 최상위 최적화 목표는 **동일하거나 더 높은 성공률을 유지하면서 더 적은 토큰·API 호출·시간·비용으로 작업을 끝내는 것**이다. 핵심 지표는 `tokens/task`가 아니라 **cost per successfully completed task**다.

```text
User Goal
  ↓
Triage (Flash)
  ↓
Planner (Flash 기본 / COMPLEX만 Pro)
  ↓
Coder (Flash)
  ↓
Reviewer (Flash)
  ↓
Debugger (필요 시 Flash → 마지막 복구 Pro)
  ↓
Re-review / Done
```

## 현재 상태

- Phase 1 — Agent Core: 완료
- Phase 2 — Code Modification: 완료
- Phase 3 — Remote Operation: 진행 중

현재 구현된 핵심 기능:

- DeepSeek V4 streaming / tool calling / thinking
- Planner Flash-first, Pro-on-demand 모델 라우팅
- Reviewer ↔ Debugger 상태 기반 자기수정 루프
- read/write/edit/bash/grep/list 도구 + 승인 게이트
- Docker Sandbox, git checkpoint, unified diff
- Tool result pruning + 75% context compaction + 95% hard block
- DeepSeek cache hit/miss 계측 + stable prefix hash
- selective Skill retrieval + `save_skill` 기반 Self-Improving Skills
- read-only tool 병렬 prefetch
- 429/5xx/timeout 및 reasoning_content 오류 recovery
- PostgreSQL 세션/메시지/태스크/agent run 영속화
- Agent Run telemetry, 성공률·비용·cache·Pro 승격 지표 API
- 동일 세션 동시 run 가드와 실행 중 메시지 injection
- 서버 재시작 시 중단된 run 감지·정리(실행 자체 재개는 미구현)
- JSONL durable action/event log
- `/sessions/{id}/status` 기반 running/role/activity/승인·질문 대기 상태 조회
- 승인·질문 600초 timeout + cancel 시 pending future 해제
- workspace 필수 선택 및 파일 브라우저 workspace 경계 제한
- 모바일 PWA: 세션/칸반/Git/파일/Skills/metrics/승인·질문/실시간 활동

## Remote Runtime

브라우저 SSE가 끊겨도 서버 run은 계속될 수 있으며 PWA는 `/status` 폴링으로 현재 role과 activity를 복구한다. 서버 프로세스 자체가 재시작된 경우 DB의 `sessions.running`을 reconcile해 중단 사실을 히스토리에 남긴다. **프로세스 재시작 후 실행 지점부터 자동 resume하는 durable worker는 아직 구현되지 않았다.**

## 효율 전략

1. Flash-first / Pro-on-demand
2. Stable prompt prefix와 cache hit 추적
3. 관련 Skill만 최대 N개 선택 삽입
4. 긴 tool result model-free pruning
5. read-only tool 병렬 실행
6. 75% context pressure에서 비파괴 compaction
7. 실패 시에만 retry / debugger / Pro escalation
8. 실제 telemetry로 `cost per successfully completed task` 비교

## 시작하기

```bash
docker compose up -d
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790
```

프론트엔드:

```bash
cd frontend
npm install
npm run build
```

## 주요 문서

- [`docs/spec.md`](docs/spec.md) — 현재 요구사항과 범위
- [`docs/architecture.md`](docs/architecture.md) — 실제 시스템 구조
- [`docs/agent-loop.md`](docs/agent-loop.md) — Agent Runtime 흐름
- [`docs/feat.md`](docs/feat.md) — 기능 구현 현황
- [`docs/db-schema.md`](docs/db-schema.md) — DB/telemetry 구조
- [`docs/benchmark.md`](docs/benchmark.md) — 비용·성능 benchmark 기준
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — 운영 이슈/해결 기록
- [`docs/work_status.md`](docs/work_status.md) — 구현 상태와 다음 작업
- [`docs/proposal/`](docs/proposal/) — 외부 Agent 설계 차용 제안(역사/로드맵 문서)

## 다음 핵심 과제

- 실제 worker 수준의 durable resume / event replay
- Tool Script/RPC Mode
- Scheduled / Condition Jobs + Web Push
- ExecutionBackend(Local→SSH→Docker) 추상화
- isolated subagent는 기반 안정화 이후 검토

## 라이선스

MIT
