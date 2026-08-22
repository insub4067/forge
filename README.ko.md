# FORGE

[English](README.md) | **한국어**

셀프호스팅 **Agent Runtime 기반 코딩 AI 플랫폼**. 자연어 목표를 받아 실행·검토·수정을 반복하고, Mac에서 장시간 작업하며 모바일 PWA로 원격 제어한다.

최상위 목표는 **동일하거나 더 높은 성공률을 유지하면서 더 적은 토큰·API 호출·시간·비용으로 작업을 끝내는 것**이다. 핵심 지표는 `tokens/task`가 아니라 **cost per successfully completed task**다.

```text
User Goal
  ↓
Triage (Flash)
  ├─ CHAT → Chat
  ├─ SIMPLE → Coder → Reviewer
  └─ COMPLEX → Planner → Coder → Reviewer
                              ↓ 필요 시
                         Debugger ↔ Reviewer
```

SIMPLE 작업은 Planner를 생략한다. 짧은 작업에서 Planner의 과탐색·context 재전송 비용을 없애고, 복잡한 작업에만 계획 단계를 사용한다.

## ⚠️ 보안 경고

FORGE는 파일 수정, shell 실행, Git 변경뿐 아니라 현재 **Mac host PTY Terminal, 화면 보기, 카메라 보기**까지 제공한다. 공용 인터넷에 직접 노출하지 말 것.

Cloudflare Tunnel 자체는 사용자 인증이 아니다. 원격 사용 시 **Cloudflare Zero Trust / Access, Tailscale, VPN 등 별도 접근제어**를 사용한다. 현재 개발 배포는 Cloudflare Zero Trust Access 정책으로 제한한다.

특히 Host Terminal은 사실상 원격 shell이다. application-level WebSocket authorization과 네트워크 경계를 독립적으로 검증해야 한다.

## 현재 구현

- DeepSeek V4 streaming / tool calling / thinking
- SIMPLE Planner bypass + COMPLEX planning
- Flash-first / Pro-on-demand routing
- Reviewer ↔ Debugger 자기수정 루프
- context pruning / 75% compaction / 95% hard block
- cache hit/miss telemetry + selective Skills
- reasoning_content 400 recovery 및 session 반복 retry 제거
- read/write/edit/bash/grep/list + approval
- `build_frontend` host build 도구: FORGE가 자기 프론트 수정 후 production build까지 수행
- Docker Sandbox 기본 + `SANDBOX_MODE=host` opt-in
- PostgreSQL persistence / agent telemetry / JSONL event log
- SSE 단절 후 `/status` polling 및 pending approval 복구
- 모바일 PWA: Session / 예약 / Mac 중심 원격 운영
- Git / Files / Skills / Metrics / Kanban / Vision
- Mac view-only 화면 보기
- Mac host PTY + WebSocket + xterm.js Terminal
- Mac Camera `imagesnap` JPEG polling PoC
- 예약 작업 기반 및 workspace fallback

## 아직 중요한 미완료

- 서버 재시작 후 실제 run continuation을 위한 Durable Worker / authoritative event replay
- Terminal/Screen/Camera authorization 보안 검증
- Scheduled / Deferred / Condition Jobs 완성 + Web Push
- Tool Script/RPC Mode
- ExecutionBackend 추상화
- bounded RSI: candidate branch → benchmark → promotion/rollback

FORGE는 자기 코드를 수정하고 일부 빌드까지 수행할 수 있지만, 자동 평가·선택 루프가 닫히기 전에는 완전한 RSI로 간주하지 않는다.

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

## 문서

[`docs/README.md`](docs/README.md)를 authoritative 문서 인덱스로 사용한다.

- `docs/core/` — 현재 구조와 Agent loop
- `docs/status/` — 실제 구현 상태
- `docs/operations/` — benchmark / troubleshooting
- `docs/planning/` — roadmap
- `docs/proposal/` — 제안 및 adoption 기록
- `docs/agents/` — **실제 runtime prompt**

## 라이선스

MIT
