# FORGE

LLM을 두뇌로 활용하는 셀프호스팅 **Agent Runtime 기반 코딩 AI 플랫폼**.
자연어 요구사항을 받아 계획 → 탐색 → 실행 → 검증 → 개선을 반복하는 자율 코딩 에이전트다.

FORGE의 핵심 방향은 거대한 모델 한 번의 호출로 해결하는 방식이 아니라, **저비용 LLM 호출을 반복하는 Agent Loop**를 통해 안정적으로 문제를 해결하는 것이다.

```
User Goal
    ↓
Planner
    ↓
Tool Execution
    ↓
Observation
    ↓
Reflection
    ↓
Next Action
    ↓
Repeat Until Done
```

## 현재 상태

**Phase 1 — Agent Core** 진행 중.
코드 읽기·분석(read_file / list_dir / grep)까지 동작하며, DeepSeek V4 Pro의 추론(thinking)과 도구 호출을 SSE로 스트리밍한다.

자세한 진행 상황은 [`docs/work_status.md`](docs/work_status.md) 참고.

## 핵심 철학

- LLM은 두뇌, Agent Runtime은 실행 시스템
- 한 번의 완벽한 답보다 반복 가능한 문제 해결 루프 지향
- Tool 실행 결과를 관찰하고 다음 행동을 결정
- 비용 효율적인 모델 호출로 장시간 작업 수행

## 기능

- Agent Loop — Planner → Tool → Observation → Reflection 반복
- DeepSeek V4 Pro — streaming + tool calling + thinking mode
- Docker Sandbox — 격리된 코드 실행 (non-root, 리소스 제한)
- 승인 게이트 — 위험 도구 실행 전 승인
- SSE Streaming — `{seq, type, data}` 이벤트 실시간 전송
- Context Management — 토큰 사용량·Logical Budget 관리
- Session Handoff — 장기 작업을 위한 HANDOFF 생성
- Mobile PWA — 진행 확인·승인·원격 제어

## 시작하기

### 요구사항

- Docker + Docker Compose
- Python 3.12+
- Node.js 18+

### 1. 인프라 실행

```bash
docker compose up -d
```

### 2. 백엔드

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790
```

### 3. 프론트엔드

```bash
cd frontend
npm install
npm run build
```

## 구조

```
forge/
├── backend/app/
│   ├── main.py
│   ├── api/
│   ├── runtime/agent.py
│   ├── llm/deepseek.py
│   ├── tools/
│   ├── sandbox/
│   └── db/
├── frontend/
├── sandbox/
├── docker-compose.yml
└── docs/
```

## 문서

- [`docs/spec.md`](docs/spec.md) — 요구사항 정의서
- [`docs/architecture.md`](docs/architecture.md) — 시스템 아키텍처
- [`docs/agent-loop.md`](docs/agent-loop.md) — Agent Loop 설계
- [`docs/work_status.md`](docs/work_status.md) — 작업 진행 상태

## 라이선스

MIT
