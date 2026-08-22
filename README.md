# FORGE

LLM을 두뇌로 활용하는 셀프호스팅 **Agent Runtime 기반 코딩 AI 플랫폼**. 자연어 요구사항을 받아 계획 → 탐색 → 수정 → 검증 → 보고를 자율 수행하고, 모바일 PWA로 원격 제어한다.

## 현재 상태

**Phase 1 — Agent Core** 진행 중. 코드 읽기·분석(read_file / list_dir / grep)까지 동작하며, DeepSeek V4 Pro의 추론(thinking)과 도구 호출을 SSE로 스트리밍한다.

자세한 진행 상황은 [`docs/work_status.md`](docs/work_status.md) 참고.

## 기능

- Agent Loop — Planner → Tool Loop → Observation → Report
- DeepSeek V4 Pro — streaming + tool calling + thinking mode
- Docker Sandbox — 격리된 코드 실행 (non-root, 리소스 제한)
- 승인 게이트 — 위험 도구 실행 전 승인 (Phase 2)
- SSE Streaming — `{seq, type, data}` 이벤트 실시간 전송
- Context Management — 토큰 사용량·버짓 관리
- Mobile PWA — 진행 확인·추론·도구 결과 표시

## 시작하기

### 요구사항

- Docker + Docker Compose
- Python 3.12+
- Node.js 18+

### 1. 인프라 실행

```bash
docker compose up -d        # postgres + redis
```

### 2. 백엔드

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # DEEP_SEEK_API_KEY 등 채우기
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8790
```

### 3. 프론트엔드

```bash
cd frontend
npm install
npm run build               # dist 생성 → FastAPI가 서빙
# 개발 모드: npm run dev (프록시로 /api → 8790)
```

### 접속

`http://localhost:8790` — 빌드된 PWA를 FastAPI가 서빙.

## 구조

```
forge/
├── backend/app/
│   ├── main.py          # FastAPI 앱
│   ├── config.py        # 설정
│   ├── api/routes.py    # SSE + REST
│   ├── runtime/agent.py # Agent Runtime
│   ├── llm/deepseek.py  # DeepSeek Adapter
│   ├── tools/registry.py# 도구
│   ├── sandbox/executor.py
│   └── db/              # SQLAlchemy 모델
├── frontend/            # Vue3 + Vite PWA
├── sandbox/Dockerfile   # 격리 실행 이미지
├── docker-compose.yml
└── docs/                # 문서
```

## 문서

- [`docs/spec.md`](docs/spec.md) — 요구사항 정의서
- [`docs/architecture.md`](docs/architecture.md) — 시스템 아키텍처
- [`docs/feat.md`](docs/feat.md) — 기능 목록
- [`docs/work_status.md`](docs/work_status.md) — 작업 진행 상태

## 라이선스

MIT
