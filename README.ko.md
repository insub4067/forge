# FORGE

[English](README.md) | **한국어**

셀프호스팅 **Agentic Coding Runtime**. 자연어 목표를 받아 실제 코드를 수정하고, 요구사항과 test/build를 프로세스가 검증하고, 실패하면 제한적으로 수리하며, Mac에서 장시간 실행하고 모바일 PWA에서 원격으로 지휘한다.

## North Star

FORGE의 목표는 가장 싼 모델을 쓰는 것이 아니다.

> **적절한 모델을 강한 실행·검증·수리·복구 Harness 안에서 사용해, 사용자가 계속 맡기고 싶은 신뢰 가능한 개인 개발 에이전트를 만드는 것.**

최적화 순서는 `verified correctness → verified completion → user trust/autonomy → cost_per_verified_task → elapsed → human intervention`이다. 모델의 “완료했습니다”는 완료 조건이 아니다.

## 현재 실행 흐름

```text
Room mode
├─ chat → 읽기 전용 Chat
├─ work → 바로 Coding path
└─ auto → Triage가 chat/work 분류

Coding path
├─ simple  → Developer
└─ complex → Planner → Developer → fresh Reviewer
                          └ FAIL → Developer 수리 1회

Developer
→ 구현 전에 Acceptance Gates 등록
→ Execute
→ Generic Verification(test/build/runtime smoke)
→ Acceptance Gate Verification
→ Integration Verification
→ CompletionSummary(process-owned)
```

복잡도는 현재 Runtime이 자동 판정한다. `multi/single` 강제 모드는 코드 규칙은 남아 있지만 사용자 API/UI에는 배선돼 있지 않다.

## 신뢰성 규칙

- 코드 변경 + acceptance gate 0개는 `completed`가 될 수 없다.
- Developer가 gate를 빠뜨리면 `gate_recovery`가 Flash/최대 3 step/`update_gates` 전용으로 1회만 복구한다.
- 복구 후에도 gate가 없으면 `completed_unverified`로 끝난다.
- generic verification은 `passed / failed / unavailable`을 구분한다.
- gate는 실제 command/exit/output evidence를 저장하며, gate 실행은 `DockerSandbox.run_verify()` 안전 경계를 탄다.
- `completed`만 auto push 가능하다. `completed_unverified`는 local commit은 가능해도 push하지 않는다. `verification_failed`는 commit/push하지 않는다.
- 최종 보고는 LLM 자기서술이 아니라 gate/test/integration/commit/push 결과로 deterministic하게 생성하고 history에 영속한다.

## 모델과 Context

- 현재 provider 구현은 **DeepSeek only**다. OpenRouter/Ling 실험은 main에서 제거됐다.
- Developer 기본은 Flash + thinking, 반복 막힘 시 bounded Pro escalation. 세션별 `auto / flash / pro` 티어가 DB에 저장되고 방 전환/재시작 후 복원된다.
- Planner/Reviewer는 Flash 기반의 짧고 독립적인 context를 사용한다.
- 큰 파일은 symbol map → `find_symbol`; 긴 tool 결과는 pruning + `read_tool_result`로 필요할 때만 복구한다.
- 75%에서 compaction, 95%에서 hard block. compaction summary는 DB에 영속돼 다음 run에서도 재사용된다.
- `ROOM_MEMORY.md`는 evidence-bound 후보만 저장한다. 현재 소스가 memory보다 항상 우선한다.

## 현재 구현

- FastAPI + Vue 3/Vite PWA + PostgreSQL
- DeepSeek streaming/tool calling/thinking/vision
- adaptive Planner → Developer → Reviewer 경로 + single Developer 경로
- Acceptance Gate Ledger + Gate Recovery + deterministic CompletionSummary
- Generic/Acceptance/Integration verification + self-repo Playwright runtime smoke
- bounded repair / Pro escalation / repeated-tool guard / cancellation
- Durable Auto Resume + crash-loop guard + session별 auto-approve/model-tier 복원
- 작업당 USD budget guardrail
- Curated / Learned / Project 3-tier Skills + refinement 후보/승인/rollback
- evidence-bound Project Memory + provenance validation
- deterministic R0 benchmark **25 tasks** + checker self-test
- bounded RSI R1: isolated candidate worktree → benchmark → no-op reject → 사람 promotion
- Scheduled Jobs: one-shot/daily/interval, timezone, DB `next_run_at`, atomic claim, overlap skip, retry
- MCP stdio: `forge_execute / forge_status / forge_result / forge_cancel`
- 모바일 PWA: 세션/예약/칸반/파일/Git/Skills/Metrics/승인/steering
- Mac remote: host PTY Terminal(WebSocket), screen polling, pointer mouse/keyboard input, Camera PoC
- `FORGE_AUTH_TOKEN` 사용 시 `/api/*`와 `/uploads/*` 보호

최신 memory hardening 기준 backend suite는 **116 tests passed**가 보고됐다.

## 다음 핵심 과제

1. 실사용 dogfooding으로 gate semantic quality, false-negative, intervention 횟수를 계측한다.
2. DeepSeek-only provider를 OpenAI-compatible internal/external adapter로 일반화하되 기존 success-rate를 먼저 보존한다.
3. Scheduled `Condition/Deferred` semantics와 durable worker/process isolation을 고도화한다.
4. fresh-context worker/병렬 실행은 독립성·성공률·비용 이득이 benchmark로 확인될 때만 제한적으로 도입한다.
5. Tool Script/RPC와 ExecutionBackend 추상화도 실측 이득이 확인될 때만 진행한다.

## 보안

FORGE는 파일 수정, shell/Git, host PTY, 화면·키보드·카메라에 접근할 수 있다. 공용 인터넷에 직접 노출하지 않는다. Cloudflare Tunnel 자체는 authorization이 아니다. 원격 운영 시 Zero Trust/VPN/Tailscale 등 네트워크 경계와 `FORGE_AUTH_TOKEN`을 함께 사용한다. Host mode와 auto-approve는 신뢰하는 개인 환경에서만 사용한다.

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

[`docs/README.md`](docs/README.md)가 문서 authority map이다. 판단 순서는 **현재 코드 → `docs/core`/`docs/status` → operations/planning → proposal → archive/handoff**다.

## 라이선스

MIT
