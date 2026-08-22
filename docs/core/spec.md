# FORGE — 요구사항 정의서

**문서 버전** v0.4  
**기준일** 2026-08-22  
**목표** 개인 개발 환경에서 사용하는 셀프호스팅 Agent Runtime 기반 코딩 AI 플랫폼

## 1. 제품 목표

FORGE는 특정 LLM에 종속된 챗봇이 아니라 LLM을 판단 엔진으로 사용하는 실행 Runtime이다.

```text
요구사항 → Triage → Plan → Code/Tool → Review → Debug → Re-review → Done
```

최상위 효율 원칙:

> 동일하거나 더 높은 성공률을 유지하면서 더 적은 토큰·API 호출·시간·비용으로 작업을 완료한다.

대표 지표는 `cost per successfully completed task`다.

## 2. 현재 v1 범위

구현됨:

- DeepSeek V4 Flash/Pro/Vision 라우팅
- Planner Flash 기본, COMPLEX만 Pro
- Coder/Reviewer/Debugger 역할 분리
- Reviewer ↔ Debugger 자기수정 루프
- read/list/grep/write/edit/bash/ask_user/update_tasks/save_skill
- 승인 게이트, 질문, cancel, runtime injection
- Docker Sandbox, git checkpoint/diff
- PostgreSQL session/message/task/agent-run 영속화
- context usage, pruning, compaction, cache telemetry
- selective Skills + session search
- SSE + `/status` polling 기반 모바일 원격 제어
- JSONL durable event/action log
- run crash/restart 중단 감지 및 사용자 가시화
- metrics API와 세션별 비용/효율 집계
- workspace 필수 선택과 파일 API 경계 제한

아직 미구현 또는 부분 구현:

- 서버 재시작 후 실제 실행 stack resume
- Redis Streams 기반 worker queue/event replay
- Tool Script/RPC Mode
- Scheduled/Condition Jobs + Web Push
- SSH/Docker ExecutionBackend 추상화
- isolated subagents

## 3. Model Policy

| Role | 기본 정책 |
|---|---|
| Triage | Flash, non-thinking |
| Planner | Flash + medium thinking; COMPLEX만 Pro + high |
| Coder | Flash, non-thinking |
| Reviewer | Flash + medium thinking |
| Debugger | Flash; 반복 실패 마지막 복구만 Pro |
| Chat | Flash |
| Vision | Flash Vision |

강한 모델을 기본으로 쓰지 않는다. 성공률 데이터가 뒷받침될 때만 escalation한다.

## 4. Tool 정책

자동 실행: `read_file`, `list_dir`, `grep`  
승인 필요: `write_file`, `edit_file`, `bash`, `save_skill`

읽기 전용 다중 호출은 병렬 prefetch할 수 있다. mutation 실행 전 git SHA checkpoint를 남긴다.

파일/디렉터리 조회 API는 session의 `workspace_path` 경계를 벗어날 수 없다.

## 5. Context Management

- Logical Budget 기본값: 설정 기반
- provider 실측 `prompt_tokens`를 context pressure 기준으로 사용
- 75%: 비파괴 compaction 시도
- 95%: compaction 불가 시 hard block
- 긴 tool 결과는 model-free pruning
- DB/history 원본과 model surface를 분리
- stable prefix hash 및 cache hit/miss 기록
- Skills는 관련 상위 N개만 선택 삽입

## 6. Reliability

- reasoning_content 호환 오류 자동 회복
- 429/5xx/timeout/connection backoff retry
- 동일 tool 반복 차단
- Reviewer/Debugger 최대 cycle 제한
- 동일 session 동시 run 금지
- approval/question 600초 timeout
- cancel 시 pending wait 해제
- run crash 시 오류 메시지 저장
- 서버 재시작 시 `sessions.running` 잔여 run reconcile

주의: reconcile은 실제 run resume이 아니라 중단 감지 및 상태 정리다.

## 7. Remote Operation

PWA는 IDE 복제가 아니라 Agent 지휘 화면이다.

지원:

- 세션/워크스페이스
- live role/activity
- approval/question
- runtime steering
- Kanban task
- Git changes/history/branches
- file browser
- Skills 관리
- context/metrics
- 재접속 후 status polling

## 8. Streaming / Status

SSE 이벤트는 `{seq,type,data}` 형식이다. runtime의 `send()` 이벤트는 JSONL durable log에도 기록된다.

별도 status API는 `running`, `role`, `activity`, `waiting_for`, idle 정보를 제공한다.

향후 durable replay의 authoritative backend는 별도 worker/queue 단계에서 구현한다.

## 9. 데이터/계측

핵심 저장 대상:

- sessions
- messages
- tasks
- checkpoints
- agent_runs

집계 지표:

- success rate
- prompt/completion/cache token
- model/tool call
- retries/compactions
- Pro escalation
- review first-pass
- debugger activation
- elapsed
- estimated cost(가격 설정이 있을 때)

API:

- `GET /api/metrics/summary`
- `GET /api/rooms/{id}/metrics`

## 10. 보안/운영 원칙

- API key는 서버 측 보관
- mutation은 approval 정책 적용
- Docker 실행은 non-root/resource 제한
- workspace 밖 파일 접근 차단
- action/event log 유지
- 외부 공개 시 반드시 Cloudflare/Tailscale 등 별도 접근 제어 사용

## 11. 개발 우선순위

1. 실제 benchmark 데이터 축적
2. durable worker/resume/event replay
3. Tool Script/RPC로 model round-trip 절감
4. Scheduled/Condition Jobs + Push
5. ExecutionBackend 확장
6. subagent는 비용 대비 실익 확인 후 도입

Vector DB, 거대한 plugin framework, multi-agent는 실제 병목이 확인되기 전까지 기본 해법으로 사용하지 않는다.
