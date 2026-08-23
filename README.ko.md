# FORGE

[English](README.md) | **한국어**

셀프호스팅 **Agent Runtime 기반 코딩 AI 플랫폼**. 자연어 목표를 받아 실행하고, 실제 test/build로 검증하고, 실패하면 수리하며, Mac에서 장시간 작업하고 모바일 PWA로 원격 제어한다.

## 핵심 철학

FORGE의 목표는 단순히 **저렴하게 LLM을 돌리는 것**이 아니다.

> **저렴한 모델도 강한 Harness와 결정적 검증 프로세스 안에서 사용해, 실제 소프트웨어 작업의 품질과 완료 신뢰성을 보장하는 것**이 핵심이다.

비싼 모델의 지능에 품질을 맡기기보다 프로세스가 품질을 보증한다.

```text
저렴한 모델
  ↓
명확한 실행 루프
  ↓
도구로 실제 코드 변경
  ↓
결정적 test/build 검증
  ├─ PASS → 완료/커밋
  └─ FAIL → 진단/수리 → 재검증
                  ↓ 계속 막힐 때만 강한 모델 승격
```

따라서 최적화 순서는 다음과 같다.

1. **성공률과 결과 품질을 유지/향상한다.**
2. 검증되지 않은 결과를 완료로 인정하지 않는다.
3. 그 조건 안에서 `cost per successful task`를 낮춘다.
4. elapsed time과 human intervention을 줄인다.

토큰 절감이나 Flash 사용 자체는 목표가 아니다. 성공률을 떨어뜨려 얻은 비용 절감은 개선으로 인정하지 않는다.

## 현재 Agent 구조

```text
User Goal
  ↓
Triage
  ├─ CHAT → Chat (Flash)
  └─ AGENT → Developer (Flash + thinking)
               ↻ Plan → Execute → Self-verify/Repair
               ↓ 필요 시 Pro 승격
               ↓
          Strict Verification Gate
          test / build 실제 실행
               ├─ PASS → completed → auto commit/push 가능
               └─ FAIL → bounded repair → verification_failed
```

별도 Planner/Reviewer/Debugger를 기본 파이프라인에 두지 않고 Developer가 하나의 컨텍스트에서 설계·구현·수정을 담당한다. 모델이 "완료"라고 말하는 것은 완료 조건이 아니며, 최종 품질 판정은 프로세스의 verification gate가 담당한다.

## 현재 구현

- DeepSeek V4 / OpenRouter 계열 model routing, streaming/tool calling/thinking
- Flash-first + 필요 시 Pro escalation
- 올인원 Developer loop
- **Strict Verification Gate**: `npm run build` / pytest 실제 실행 후 완료 판정
- 검증 실패 시 bounded repair, 재실패 시 `verification_failed`
- 검증 성공 경로에서만 auto commit/push
- step-level history persistence
- **Durable Auto Resume**: 서버 재시작 후 미완료 run을 history 기반으로 재개
- crash-loop guard / `AUTO_RESUME=0`
- PostgreSQL persistence / JSONL event log / metrics
- context pruning / compaction / cache telemetry
- Curated / Learned / Project 3-tier Skills
- 결정적 R0 benchmark harness + 21개 task
- bounded RSI promotion gate(`success_rate → cost_per_success → elapsed`)
- Docker Sandbox 기본 + Host mode opt-in
- application-level API/WebSocket auth(`FORGE_AUTH_TOKEN`)
- 모바일 PWA: 세션 / 예약 / 맥
- Git / Files / Skills / Metrics / Kanban / Vision
- Mac host PTY Terminal / 화면 보기 / Camera PoC
- 예약 작업 기반

## 현재 중요한 미완료

- Durable Resume의 approval/capability 안전 경계 고도화
- verification을 `PASSED / FAILED / UNAVAILABLE`로 엄밀히 구분
- benchmark 규모/난이도 확대 및 외부 harness 비교
- candidate worktree 실행 + benchmark + 사람 승인까지 이어지는 bounded RSI R1 완성
- Scheduled / Deferred / Condition Job의 restart/idempotency/timezone semantics 완성
- Tool Script/RPC Mode
- ExecutionBackend(Local/Docker/SSH) 정리

## 보안

FORGE는 파일 수정, shell, Git, host PTY Terminal, 화면/카메라 접근 권한을 가진다. 공용 인터넷에 직접 노출하지 않는다.

Cloudflare Tunnel 자체는 authorization이 아니다. 원격 사용 시 Cloudflare Zero Trust / Access, Tailscale, VPN 등 별도 접근통제를 사용하고 `FORGE_AUTH_TOKEN` 기반 application auth도 독립적으로 유지한다.

## 시작하기

```bash
docker compose up -d
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790
```

Frontend:

```bash
cd frontend
npm install
npm run build
```

## 문서

[`docs/README.md`](docs/README.md)를 authoritative 문서 인덱스로 사용한다. Proposal/Archive보다 실제 코드와 `docs/core`, `docs/status`를 우선한다.

## 라이선스

MIT
