# Hermes Agent 기술 도입 제안서

> 대상: FORGE
> 참고 프로젝트: NousResearch/hermes-agent
> 목적: Hermes Agent의 검증된 설계 아이디어를 FORGE의 저비용·장시간·모바일 원격 코딩 에이전트 목표에 맞게 선택적으로 도입한다.

## 1. 배경

FORGE는 DeepSeek API를 역할별로 반복 호출하면서 실제 코드베이스의 문제를 해결하고, 모바일 PWA에서 장시간 실행 작업을 원격 제어하는 코딩 에이전트를 목표로 한다.

Hermes Agent는 FORGE와 겹치는 문제를 이미 다수 해결하고 있다.

- 장시간 살아 있는 agent core
- 세션 간 memory
- 경험에서 skill을 생성하고 개선하는 learning loop
- isolated subagent와 병렬 작업
- 여러 tool 호출을 script/RPC로 묶는 실행 방식
- CLI와 messaging gateway를 동일 agent core에 연결
- scheduled automation
- local/Docker/SSH/cloud sandbox 실행 backend
- prompt cache를 최우선 제약으로 취급하는 architecture
- core tool을 최소화하고 capability를 skill/plugin/MCP 쪽으로 밀어내는 narrow-waist 구조

FORGE가 Hermes 전체를 복제할 필요는 없다. FORGE의 강점은 작은 Python runtime, DeepSeek의 비용 효율, 모바일 원격 제어다. 따라서 Hermes에서 장기 실행 비용과 자율성에 직접 기여하는 설계만 선택적으로 흡수한다.

---

## 2. 핵심 원칙

### 2.1 Core is a narrow waist

AgentRuntime을 기능 저장소로 만들지 않는다.

FORGE core가 책임질 것은 다음 정도로 제한한다.

- model loop
- context assembly
- task state
- tool dispatch
- approval/security
- cancellation
- event/session lifecycle
- recovery

새 capability는 가능한 한 다음 순서로 추가한다.

```text
기존 capability 확장
→ Skill
→ 조건부 Tool
→ Plugin / MCP
→ Core Tool (최후의 수단)
```

모든 core tool schema는 모델 요청마다 context 비용을 발생시킬 수 있으므로 core tool 증가는 비용 증가로 취급한다.

### 2.2 Prompt cache first

장시간 세션에서는 system prompt와 stable prefix가 가능한 한 byte-stable해야 한다.

```text
Stable Prefix
├─ system instructions
├─ project instructions
├─ core tool definitions
└─ stable memory

Dynamic Tail
├─ current user request
├─ recent agent messages
├─ tool calls/results
└─ steering
```

대화 중 toolset이나 system prompt를 불필요하게 재구성하지 않는다.

Context compaction만 명시적인 prefix 변경 경계로 취급한다.

---

## 3. S급: Self-Improving Skills

Hermes에서 FORGE가 가장 적극적으로 가져올 가치가 있는 기능이다.

현재 FORGE는 Planner/Coder/Reviewer가 매 작업을 새롭게 해결한다. 동일한 종류의 문제를 여러 번 해결해도 그 절차 자체가 reusable capability로 남지 않는다.

이를 다음 구조로 발전시킨다.

```text
Task
→ Agent execution
→ Reviewer evaluation
→ useful reusable pattern 발견
→ Skill candidate
→ 검증
→ SKILL.md 생성/수정
→ 다음 관련 작업에서 선택적 로드
→ 결과 기반 개선
```

### Skill 예시

```text
skills/
  fastapi-debug/
    SKILL.md
  vue-pwa-review/
    SKILL.md
  ios-build-fix/
    SKILL.md
  git-regression-review/
    SKILL.md
```

Skill은 단순 memory와 구분한다.

- Memory: 사실과 과거 상태
- Skill: 문제를 해결하는 절차

예:

```text
Memory:
이 프로젝트는 Vue 3 + FastAPI를 사용한다.

Skill:
FastAPI SSE 연결 끊김을 분석할 때 확인해야 하는 순서와 명령.
```

### 자동 생성 제한

모든 작업 후 skill을 만들면 쓰레기 skill이 급증한다.

후보 조건을 둔다.

- 여러 단계의 성공적인 작업
- 반복 가능성이 높은 해결 절차
- Reviewer가 재사용 가치가 있다고 판정
- 기존 skill과 중복되지 않음

초기에는 자동 저장보다 `skill_candidate` 이벤트를 만들고 사용자 승인 후 저장하는 방식이 안전하다.

---

## 4. S급: Prompt-Cache-First Context Architecture

DeepSeek API 비용을 낮추려면 단순히 저렴한 모델을 사용하는 것만으로 부족하다.

동일 세션의 stable prefix 재사용률을 높여야 한다.

### 도입 항목

1. system prompt를 세션 중 불필요하게 변경하지 않는다.
2. core tool schema 순서와 직렬화 결과를 안정화한다.
3. project instruction과 stable memory의 삽입 순서를 고정한다.
4. 현재 작업에 필요하지 않은 capability를 core prompt에 추가하지 않는다.
5. 동적 상태는 가능한 한 tail에 둔다.
6. compaction 발생 여부와 cache invalidation을 event로 기록한다.

### 측정

향후 provider가 cache 관련 usage를 제공하면 다음을 관찰한다.

```text
input_tokens
cached_input_tokens
uncached_input_tokens
cache_hit_ratio
```

Provider가 직접 제공하지 않더라도 stable prefix hash를 기록해 세션 중 변경 여부를 추적할 수 있다.

---

## 5. S급: Tool Script / RPC Mode

현재 일반적인 tool loop는 여러 파일을 탐색하는 것만으로도 model round-trip이 반복된다.

```text
LLM
→ grep
→ LLM
→ read_file A
→ LLM
→ read_file B
→ LLM
→ git diff
→ LLM
```

탐색성 작업 중 일부는 모델 판단이 매 단계마다 필요하지 않다.

Hermes식 script/RPC 개념을 FORGE에 단순화해 도입한다.

```text
LLM
→ run_tool_script
    ├─ grep
    ├─ read_file A
    ├─ read_file B
    └─ git diff
→ aggregated result
→ LLM
```

효과:

- API 호출 감소
- latency 감소
- intermediate tool chatter 감소
- context 증가 억제

### 보안

임의 Python을 host process에서 실행하면 안 된다.

초기 구현은 제한된 DSL 또는 sandboxed script executor를 권장한다.

허용된 tool RPC만 호출 가능해야 한다.

```python
results = await tools.parallel([
    grep("AgentRuntime"),
    read_file("backend/app/runtime/agent.py"),
    git_diff(),
])
```

write/bash 같은 mutation tool은 기존 approval policy를 반드시 통과해야 한다.

---

## 6. A급: Memory와 Skill의 폐쇄형 학습 루프

FORGE의 ROOM_MEMORY/GLOBAL_MEMORY를 단순 문자열 저장소에서 curated memory로 발전시킨다.

권장 계층:

```text
Project Context
Session Summary
Project Memory
User Preferences
Skills
```

모든 과거 대화를 prompt에 넣지 않는다.

필요할 때 검색하고 요약해서 현재 context에 주입한다.

### Session search

초기에는 vector DB가 필요하지 않다.

SQLite FTS5 정도로 충분하다.

```text
session_messages
→ FTS5 index
→ keyword/hybrid retrieval
→ small result set
→ optional LLM summary
→ current context
```

이는 FORGE의 단순한 배포 철학과도 맞는다.

---

## 7. A급: Agent Core와 Interface 완전 분리

Hermes는 동일 agent core를 CLI와 messaging gateway 등에서 사용한다.

FORGE 역시 PWA가 agent lifecycle의 주인이 되면 안 된다.

```text
           FORGE Agent Core
                  │
       ┌──────────┼──────────┐
       │          │          │
      PWA        CLI        API
       │
     iPhone
```

브라우저 연결이 끊겨도 Agent Core는 계속 실행한다.

클라이언트는 다음 역할만 가진다.

- command 제출
- event 구독
- approval 응답
- steering
- cancellation
- 결과 조회

이 구조는 durable event log proposal과 함께 구현한다.

---

## 8. A급: Execution Backend Abstraction

Tool 실행 위치를 AgentRuntime과 분리한다.

초기 interface 예:

```python
class ExecutionBackend:
    async def run(self, command: str): ...
    async def read_file(self, path: str): ...
    async def write_file(self, path: str, content: str): ...
```

구현 우선순위:

```text
LocalBackend
→ SSHBackend
→ DockerBackend
```

Modal/Daytona/Vercel Sandbox 같은 cloud backend는 실제 필요가 생긴 뒤 검토한다.

이를 통해 FORGE가 설치된 Mac에서 다른 서버나 개발 환경을 작업 대상으로 사용할 수 있다.

---

## 9. A급: Scheduled Autonomous Development

FORGE를 사용자가 메시지를 보낼 때만 움직이는 agent에서 비동기 개발 agent로 확장한다.

예:

```text
03:00
→ git fetch
→ tests
→ dependency/security checks
→ regression 발견
→ agent analysis
→ 모바일 알림
```

또는:

```text
Agent가 PR push
→ CI 완료 조건 감시
→ 실패
→ 로그 분석
→ 수정
→ push
→ 재검증
```

Scheduler는 AgentRuntime에 직접 cron 구현을 섞기보다 job abstraction으로 분리한다.

```text
ScheduledJob
ConditionJob
DeferredJob
```

Phase 3의 durable worker/recovery 이후 구현하는 것이 적절하다.

---

## 10. B급: Isolated Subagents

Hermes의 parallel delegation도 가치가 있지만 FORGE에서는 기반 안정화 이후 도입한다.

Coordinator가 독립적인 workstream만 병렬화한다.

```text
Coordinator
├─ Worker A: backend 분석
├─ Worker B: frontend 분석
└─ Worker C: tests 분석

→ 결과 취합
→ main agent 판단
```

Worker에 전체 main context를 복제하지 않는다.

Coordinator가 self-contained task packet을 만들어 전달한다.

이렇게 해야 병렬화가 context 비용 폭증으로 이어지지 않는다.

---

## 11. B급: Behavior Contract 중심 테스트

Hermes의 개발 원칙 중 FORGE에도 적용할 가치가 높다.

현재 값 자체를 snapshot으로 고정하는 테스트보다 invariant를 테스트한다.

예:

나쁜 테스트:

```text
tool count == 12
```

좋은 테스트:

```text
mutation tool은 반드시 approval required
cancelled session은 추가 tool dispatch 금지
review success는 unresolved task가 없어야 함
```

특히 다음은 E2E 검증을 우선한다.

- config propagation
- tool permission
- git checkpoint
- cancellation
- remote backend
- context compaction
- session recovery

---

## 12. FORGE에 가져오지 않을 것

Hermes의 모든 기능을 복제하지 않는다.

당장 도입하지 않는다.

- Telegram/Discord/WhatsApp 등 다수 messenger adapter
- 거대한 plugin ecosystem
- 다수 cloud sandbox backend
- voice/TTS 기능
- 범용 personal assistant 기능
- 연구용 trajectory generation
- 외부 서비스 통합을 core에 직접 추가하는 구조

FORGE의 제품 중심은 코딩과 모바일 원격 제어다.

---

## 13. 기존 proposal과의 통합

### DeepSeek Harness에서 가져오는 것

- context compaction
- tool-result pruning
- durable event log
- provider recovery
- inbox/steering
- cancellation semantics

### Claude Code 설계에서 가져오는 것

- task lifecycle
- coordinator/worker
- permission boundary
- isolated execution

### Hermes Agent에서 가져오는 것

- self-improving skills
- prompt-cache-first architecture
- tool script/RPC mode
- narrow-waist core
- memory/skill learning loop
- execution backend abstraction
- scheduled autonomous jobs

### FORGE가 독자적으로 유지할 것

- DeepSeek 중심 저비용 model routing
- Planner/Coder/Reviewer/Debugger 역할 구조
- Vue PWA 기반 모바일 원격 UX
- 작고 이해 가능한 Python core
- self-hosted Mac-first deployment

---

## 14. 권장 구현 순서

### Phase H1 — 비용과 장기 실행 기반

1. Stable prompt/context assembly
2. Context compaction + tool result pruning
3. Provider retry/recovery
4. Durable event log

### Phase H2 — 학습

5. Skill storage format
6. Skill retrieval
7. Reviewer 기반 skill candidate 생성
8. 사용자 승인 기반 skill 저장
9. Skill usage feedback 및 개선

### Phase H3 — Tool 효율

10. ToolExecutor 정리
11. read-only parallel tools
12. restricted Tool Script/RPC mode
13. mutation approval integration

### Phase H4 — Persistent Agent

14. Agent Core / PWA lifecycle 분리
15. session reconnect/replay
16. scheduled jobs
17. condition jobs
18. push notification

### Phase H5 — 확장 실행

19. ExecutionBackend interface
20. SSHBackend
21. DockerBackend
22. isolated worker/subagent

---

## 15. 성공 기준

Hermes 기술 도입은 기능 개수로 평가하지 않는다.

다음 지표가 개선되어야 한다.

### 비용

- 동일 복잡도 작업의 model round-trip 감소
- cache-friendly prefix 유지
- tool chatter token 감소

### 지속성

- context limit 이전에 compaction으로 작업 지속
- 브라우저 연결 종료 후 agent 작업 지속
- 서버/worker 재시작 후 session 복구

### 자율성

- 반복 문제 해결 시 기존 skill 재사용
- 복잡한 성공 경험에서 reusable skill 생성
- CI/예약 작업을 사용자 개입 없이 이어서 처리

### 품질

- Reviewer 실패 후 수정/재검증 성공률
- 반복 작업의 성공률 증가
- skill 적용 후 평균 tool/model step 감소

---

## 16. 최종 방향

FORGE는 Hermes Agent의 범용 personal-agent 제품을 복제하지 않는다.

목표는 다음 조합이다.

```text
DeepSeek Harness
  → 오래 살아남는 runtime

Claude Code
  → 강한 coding task orchestration

Hermes Agent
  → 학습하고 비용을 줄이는 persistent agent

FORGE
  → 모바일에서 원격 조종 가능한 저비용 코딩 에이전트
```

최종적으로 FORGE는 매 작업을 처음부터 다시 생각하는 stateless coding assistant가 아니라, 프로젝트에서 성공한 해결 절차를 축적하고 재사용하며 장시간 독립적으로 실행되는 개인 개발 agent가 되어야 한다.

가장 먼저 구현할 Hermes 계열 기능은 **Self-Improving Skills**, **Prompt-Cache-First Context**, **Tool Script/RPC Mode** 세 가지다.