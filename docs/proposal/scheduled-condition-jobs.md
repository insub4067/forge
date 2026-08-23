# Scheduled / Condition Jobs 도입 제안

> 상태: Proposal (J0·J1 일부 구현됨 — one-shot/daily/interval, timezone, restart 복원, 중복 방지, retry, DST 안전)  
> 목표: FORGE를 사용자가 직접 메시지를 보낼 때만 움직이는 코딩 에이전트에서, 지정 시간·반복 주기·조건에 따라 스스로 작업을 시작하는 persistent development agent로 확장한다.

## 1. 배경

현재 FORGE는 사용자의 요청을 받아 즉시 AgentRuntime을 실행하는 구조다.

하지만 실제 개발/운영 업무에는 다음과 같은 요청이 많다.

- 오늘 18시에 테스트 돌려줘
- 매일 오전 7시에 로그 확인해줘
- 매주 일요일 밤 10시에 전체 테스트해줘
- PR 생성 후 CI가 끝나면 결과 확인해줘
- 테스트가 실패하면 원인 분석하고 수정해줘
- 특정 파일/브랜치/상태가 바뀌면 다시 작업해줘

이러한 요청을 직접 지원하면 FORGE는 단순 원격 코딩 UI를 넘어 **Mac에서 계속 살아 있는 개인 개발 Agent Runtime**으로 발전할 수 있다.

---

## 2. 핵심 원칙

Scheduler가 별도의 Agent 구현이 되어서는 안 된다.

예약/조건 시스템의 역할은 **언제 기존 AgentRuntime을 호출할 것인가를 결정하는 것**이다.

```text
User Request
    ↓
Intent / Job Parsing
    ↓
┌─────────────────────────────┐
│ Immediate Task              │ → 기존 AgentRuntime
│ Scheduled Job               │
│ Deferred Job                │
│ Condition Job               │
└─────────────────────────────┘
              ↓
           Job Store
              ↓
        Scheduler / Watcher
              ↓
        기존 AgentRuntime
              ↓
Planner → Coder → Reviewer → Debugger
```

AgentRuntime의 model/tool/context 정책을 별도로 복제하지 않는다.

---

## 3. Job 종류

### 3.1 ScheduledJob

특정 시각 또는 반복 주기에 실행한다.

예:

```text
오늘 18시에 테스트 실행해
매일 오전 7시에 로그 점검해
매주 월요일 09시에 dependency 상태 확인해
```

지원 형태:

- one-shot datetime
- daily
- weekly
- interval
- cron-like recurrence

### 3.2 DeferredJob

현재 시점을 기준으로 일정 시간이 지난 뒤 한 번 실행한다.

```text
30분 뒤 다시 테스트해
3시간 후 CI 결과 확인해
```

### 3.3 ConditionJob

특정 조건이 만족될 때 Agent를 실행한다.

예:

```text
CI가 실패하면 분석해
새 GitHub issue가 생기면 검토해
테스트가 실패하면 수정해
특정 브랜치에 새 commit이 생기면 리뷰해
```

초기에는 polling 가능한 조건부터 지원한다.

Webhook/event integration은 실제 필요가 있을 때 별도 확장한다.

---

## 4. 자연어 UX

사용자는 별도 cron 문법을 몰라도 된다.

예:

```text
"오늘 저녁 6시에 trade-bot 테스트 돌려줘"
```

Agent/UI는 이를 다음처럼 확인한다.

```text
예약 작업

작업: trade-bot 테스트 실행
시간: 2026-08-22 18:00
시간대: Asia/Seoul
반복: 없음
Workspace: /Users/.../trade-bot

[등록] [취소]
```

반복 예:

```text
"매일 오전 7시에 서버 로그 보고 문제 있으면 알려줘"
```

```text
작업: 서버 로그 점검
시간: 매일 07:00
시간대: Asia/Seoul
반복: Daily
```

중요한 예약은 사용자가 실제 해석 결과를 확인할 수 있어야 한다.

---

## 5. 자연어 시간 파싱

초기에는 LLM에게 모든 시간 계산을 맡기지 않는다.

권장 흐름:

```text
User text
↓
LLM/Parser → structured schedule intent
↓
Deterministic datetime validation
↓
timezone normalization
↓
DB 저장
```

구조 예:

```json
{
  "type": "scheduled",
  "prompt": "전체 테스트를 실행하고 실패하면 원인을 분석해",
  "run_at": "2026-08-22T18:00:00+09:00",
  "timezone": "Asia/Seoul",
  "recurrence": null
}
```

반복 규칙은 가능하면 표준 형태로 저장한다.

후보:

- RRULE
- cron expression
- 내부 normalized schedule schema

초기 구현은 유지보수가 쉬운 형태를 선택한다.

---

## 6. Database

예상 테이블:

```text
scheduled_jobs
```

필드 예:

```text
id
session_id (nullable)
workspace_path
name
prompt
job_type
schedule
condition
 timezone
enabled
status
next_run_at
last_run_at
last_result
created_at
updated_at
```

실행 기록은 별도로 둔다.

```text
job_runs

id
job_id
agent_run_id
started_at
finished_at
status
error
```

기존 `agent_runs` telemetry와 연결한다.

Job 실행 때문에 새로운 metrics 체계를 만들지 않는다.

---

## 7. Scheduler 구현

초기 버전에서는 과도한 infrastructure를 도입하지 않는다.

PoC 후보:

- APScheduler
- asyncio background scheduler

단, 장기적으로는 Durable Worker와 결합해야 한다.

목표 구조:

```text
FastAPI Control Plane
        ↓
     Job Store
        ↓
Durable Scheduler
        ↓
   Worker Queue
        ↓
   Agent Worker
```

Scheduler가 FastAPI process 내부에만 존재하면 서버 재시작 동안 예약을 놓칠 수 있으므로 DB의 `next_run_at`이 authoritative source여야 한다.

---

## 8. 서버 재시작 복구

예약 작업은 process memory에만 있으면 안 된다.

서버 시작 시:

```text
DB load
→ enabled job 조회
→ missed execution 계산
→ next_run_at 복원
→ scheduler 등록
```

### Missed Job 정책

예:

03:00 예약
03:00~03:15 서버 다운
03:15 서버 시작

정책이 필요하다.

후보:

- 즉시 catch-up
- skip
- 일정 grace period 내에서만 catch-up

권장 기본값:

```text
one-shot: grace period 내면 실행
recurring: 가장 최근 1회만 catch-up
오래 지난 반복 실행은 누적 실행하지 않음
```

설정 가능하게 한다.

---

## 9. 중복 실행 방지

같은 Job이 이전 실행을 끝내지 않았는데 다음 주기가 도착할 수 있다.

정책 예:

```text
ALLOW
SKIP
QUEUE_ONE
```

기본은 `SKIP` 또는 `QUEUE_ONE`이 안전하다.

예:

```text
매 10분 실행
이전 작업이 아직 running
→ 중복 AgentRun 2개 생성 금지
```

Job 단위 lock/idempotency가 필요하다.

기존 session concurrent-run guard와도 충돌하지 않게 설계한다.

---

## 10. Workspace / Session

예약 작업은 반드시 실행 대상 workspace를 명확히 가져야 한다.

등록 시 현재 session workspace를 snapshot 한다.

```text
Job
├─ prompt
├─ workspace_path
├─ execution policy
└─ optional session_id
```

기존 채팅 session에 결과를 남길 수도 있고, scheduled run 전용 session을 자동 생성할 수도 있다.

초기 권장:

- Job마다 owner session을 유지
- 실행 결과를 해당 session history에 기록
- 장기적으로 run history는 job detail에서 별도 조회

---

## 11. 승인 정책

예약 Agent가 사용자가 자고 있는 동안 write/bash 승인을 기다리면 의미가 없다.

따라서 Job별 execution policy가 필요하다.

예:

```text
Manual Approval
Auto Read-Only
Trusted Workspace Auto
```

초기에는 보수적으로 간다.

### 기본

- read/list/grep: 자동
- mutation: 기존 approval 유지

### 향후 Trusted Job

사용자가 명시적으로 특정 Job에 한해 자동 실행 범위를 승인할 수 있다.

예:

```text
이 예약 작업은 테스트 실행까지만 자동 승인
파일 수정은 승인 필요
```

전체 host shell 권한을 묵시적으로 부여하지 않는다.

---

## 12. Notification / Web Push

예약 실행은 사용자가 화면을 보고 있지 않을 가능성이 높다.

따라서 Push와 강하게 연결된다.

알림 대상:

- Job 시작
- 작업 완료
- 실패
- 승인 필요
- 사용자 질문 필요
- condition 충족
- 반복 실패

예:

```text
FORGE
매일 테스트 작업 완료
3개 테스트 실패 — 확인 필요
```

PWA Web Push를 우선 검토한다.

Desktop Tauri가 구현되면 OS notification도 같은 Agent Event를 소비한다.

---

## 13. Condition Job

ConditionJob은 매번 전체 Agent를 호출하면 비용 낭비가 커질 수 있다.

따라서 2단계 구조가 적합하다.

```text
Cheap Watcher
    ↓ condition true
AgentRuntime
```

예:

```text
CI status API polling
→ success: 아무것도 안 함
→ failure: Agent 실행
```

Watcher 자체는 가능한 한 deterministic code로 처리한다.

LLM을 hourly polling engine으로 사용하지 않는다.

FORGE의 비용 효율 원칙과 직접 연결된다.

---

## 14. Scheduled Job 예시

### Daily Repository Health Check

```text
매일 03:00
→ git fetch
→ status 확인
→ test 실행
→ dependency/security check
→ 문제 없음: 기록만
→ 문제 있음: Agent 분석
→ 모바일 Push
```

### CI Recovery

```text
PR push
→ Condition Job 생성
→ CI 상태 polling
→ failure 감지
→ 로그 수집
→ Debug Agent 실행
→ 수정
→ push
→ condition 재검증
```

### Weekly Maintenance

```text
매주 일요일 22:00
→ 전체 테스트
→ lint
→ dead code 후보
→ dependency update 후보
→ 보고서 생성
```

---

## 15. Agent Runtime과의 경계

Job scheduler가 Agent reasoning을 직접 하지 않는다.

```text
Scheduler responsibility
- when
- whether
- concurrency
- persistence
- retries for scheduling infrastructure

AgentRuntime responsibility
- plan
- code
- tool use
- review
- debug
- task completion
```

이 경계를 유지한다.

---

## 16. Agent 자체 Retry와 Job Retry 분리

둘을 혼동하면 안 된다.

### Agent Retry

429 / provider timeout / debugger loop 등의 현재 Runtime recovery.

### Job Retry

Scheduler 자체 오류 또는 Worker crash 등 Job execution infrastructure 실패.

예:

```text
Job started
→ Worker crash before AgentRun completion
→ durable worker 정책에 따라 resume/retry
```

동일 작업을 처음부터 무한 재실행하지 않는다.

---

## 17. 비용 제한

예약 작업은 사람이 보고 있지 않아 runaway 비용 위험이 더 크다.

Job별 budget을 검토한다.

예:

```text
max_model_calls
max_agent_runs_per_day
max_cost_per_run
max_duration
```

초기에는 현재 Runtime step/review limit을 그대로 사용하고, 이후 telemetry 데이터 기반으로 Job budget을 추가한다.

Global daily budget도 장기적으로 고려할 수 있다.

---

## 18. UI

PWA에 `예약 작업` 화면을 추가한다.

예:

```text
Scheduled Jobs

● Daily Test
  매일 07:00
  다음 실행: 내일 07:00
  Workspace: forge

● CI Watch
  조건 대기 중

○ Weekly Review
  매주 일요일 22:00
  Disabled
```

상세:

- 작업명
- prompt
- workspace
- schedule/condition
- timezone
- enabled
- next run
- last run
- last result
- run history
- edit
- disable
- delete
- Run Now

모바일 우선으로 단순하게 설계한다.

---

## 19. API

예시:

```text
GET    /api/jobs
POST   /api/jobs
GET    /api/jobs/{id}
PATCH  /api/jobs/{id}
DELETE /api/jobs/{id}
POST   /api/jobs/{id}/run
GET    /api/jobs/{id}/runs
```

정확한 path는 현재 FastAPI routing convention에 맞춘다.

---

## 20. Security

예약 작업은 remote code execution과 유사한 권한을 장시간 자동화한다.

따라서 특히 중요하다.

- FORGE public exposure 금지
- Cloudflare Zero Trust / VPN 등 외부 접근 제어 권장
- workspace boundary 유지
- host mode 위험 경고
- destructive command policy 유지
- Job 변경/삭제 audit event 기록
- schedule 생성 시 사용자 identity 추적 가능 구조 고려

Job prompt 자체도 untrusted external event로 변경될 수 없도록 한다.

---

## 21. Telemetry

Job별 최소 지표:

- trigger_count
- run_count
- success_count
- failure_count
- skipped_count
- average elapsed
- model/token/cost totals
- Pro escalation
- approval waits

핵심 비교:

```text
자동화로 절감한 인간 개입
vs
추가 inference 비용
```

전체 최적화 원칙은 계속:

**cost per successfully completed task**

이다.

---

## 22. 구현 순서

### Phase J0 — One-shot Scheduled Job

- DB schema
- one-shot datetime
- timezone
- basic scheduler
- 기존 AgentRuntime 실행
- Job list API
- restart 후 schedule 복원

성공 기준:

```text
"10분 뒤 테스트해"
→ DB 등록
→ 지정 시각 Agent 실행
→ 결과 저장
```

### Phase J1 — Recurring Jobs

- daily/weekly
- recurrence
- missed-run policy
- overlap policy
- enable/disable
- PWA 관리 UI

### Phase J2 — Notifications

- Web Push
- approval/question notification
- 완료/실패 notification

### Phase J3 — Condition Jobs

- deterministic watcher abstraction
- polling interval
- condition state persistence
- condition true 시 AgentRuntime 실행

### Phase J4 — Durable Worker Integration

- Scheduler와 API process 분리
- worker queue
- crash recovery
- true resume

### Phase J5 — External Events

실제 필요성이 확인될 때:

- GitHub webhook
- CI event
- 기타 MCP/plugin event

을 검토한다.

---

## 23. 우선순위 관계

현재 FORGE의 전체 roadmap에서는 Durable Worker가 Scheduled Job보다 선행하는 것이 이상적이다.

하지만 기능 검증을 위해 J0/J1 수준의 scheduler를 먼저 PoC할 수는 있다.

권장:

```text
J0 PoC
  ↓
Durable Worker
  ↓
J1/J2/J3 production hardening
```

즉 Scheduler 기능 때문에 Durable Worker 설계를 우회하는 구조를 만들지 않는다.

---

## 24. 하지 않을 것

초기에는 다음을 하지 않는다.

- Kubernetes CronJob
- Celery 전체 도입
- Temporal 같은 대규모 workflow engine
- distributed scheduler cluster
- LLM으로 매분 condition 판정
- 복잡한 workflow visual editor
- Zapier/n8n 범용 자동화 플랫폼 복제

FORGE는 범용 automation SaaS가 아니라 coding agent harness다.

---

## 25. 완료 기준

1. 자연어 요청을 예약 Job으로 등록할 수 있다.
2. 서버 재시작 후에도 예약 정보가 유지된다.
3. timezone이 명확하다.
4. 반복 실행을 지원한다.
5. 중복 실행 방지 정책이 있다.
6. 기존 AgentRuntime을 그대로 재사용한다.
7. 실행 결과와 metrics가 기존 telemetry에 연결된다.
8. 승인/보안 정책을 우회하지 않는다.
9. PWA에서 조회/수정/중지 가능하다.
10. 향후 Durable Worker와 자연스럽게 결합할 수 있다.

---

## 결론

Scheduled / Condition Jobs는 FORGE의 제품 방향과 매우 잘 맞는다.

FORGE가 최종적으로 지향해야 할 모습은:

```text
사용자 요청을 기다리는 Agent
            ↓
시간과 조건을 기억하는 Agent
            ↓
필요한 순간 스스로 작업을 시작하는 Agent
            ↓
실패를 복구하고 결과를 사용자에게 전달하는 Persistent Development Agent
```

이다.

핵심은 Scheduler 자체를 복잡하게 만드는 것이 아니라, **시간/조건이라는 Trigger를 기존 FORGE Harness 앞에 얇게 추가하는 것**이다.
