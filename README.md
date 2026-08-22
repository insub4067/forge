# FORGE

LLM을 두뇌로 활용하는 셀프호스팅 **Agent Runtime 기반 코딩 AI 플랫폼**.
자연어 요구사항을 받아 계획 → 실행 → 검토 → 수정 → 재검증을 반복하는 자율 코딩 에이전트다.

FORGE의 핵심 방향은 거대한 모델 한 번의 호출로 해결하는 방식이 아니라, **저비용 LLM 호출을 역할별로 반복하는 Agent Loop**를 통해 안정적으로 문제를 해결하는 것이다.

```
User Goal
    ↓
Triage
    ↓
Planner
    ↓
Coder
    ↓
Reviewer
    ↓
Debugger (필요 시)
    ↓
Re-review / Done
```

## 현재 상태

**Phase 1 — Agent Core 완료**  
**Phase 2 — Code Modification 완료**  
**Phase 3 — Remote Operation 진행 중**

현재 코드 읽기·수정·명령 실행, 승인 게이트, 세션/메시지 영속화, 역할별 모델 라우팅, Vision 분석, Git 상태/히스토리 확인, 모바일 PWA 원격 제어까지 구현되어 있다.

자세한 진행 상황은 [`docs/work_status.md`](docs/work_status.md) 참고.

## 핵심 철학

- LLM은 두뇌, Agent Runtime은 실행 시스템
- 한 번의 완벽한 답보다 반복 가능한 문제 해결 루프 지향
- 역할별로 모델 비용과 추론 강도를 분리
- Tool 실행 결과를 관찰하고 다음 행동을 결정
- 비용 효율적인 모델 호출로 장시간 작업 수행
- 모바일은 IDE 복제가 아니라 에이전트 지휘·승인·검증 화면을 지향

## 기능

- Agent Pipeline — Triage → Planner → Coder → Reviewer → Debugger
- Model Routing — 역할별 DeepSeek V4 Pro / Flash / Vision 모델 선택
- DeepSeek V4 — streaming + tool calling + thinking mode
- Docker Sandbox — 격리된 코드 실행 (non-root, 리소스 제한)
- 승인 게이트 — 위험 도구 실행 전 승인
- SSE Streaming — `{seq, type, data}` 이벤트 실시간 전송
- Context Management — 실제 API usage 기반 토큰 사용량·Logical Budget 관리
- Session State — goal / files_changed / errors / tasks 추적
- Git Checkpoint & Diff — 변경 전 SHA 기록, 변경 diff 표시
- Git Remote View — 변경 파일, 파일 diff, 커밋 히스토리, 브랜치 전환
- Vision Agent — 이미지가 포함된 요청 사전 분석
- Runtime Steering — 실행 중 사용자 메시지 큐잉 및 다음 스텝 반영
- Mobile PWA — 진행 확인·승인·질문 응답·원격 제어

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
│   ├── orchestrator/model_router.py
│   ├── llm/
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
