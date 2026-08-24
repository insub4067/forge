# FORGE Intent Interpreter / Task IR 제안

> 상태: Proposal
> 작성: 2026-08-25
> 목표: 현재 Triage를 단순 `chat/work` 분류기에서 **사용자 자연어를 보존하면서 FORGE가 실행하기 좋은 구조화된 의미 표현(Task IR)으로 정규화하는 얇은 Interpreter 계층**으로 발전시킨다.

## 1. 배경

현재 FORGE의 auto room은 Triage가 요청을 `chat` 또는 `work`로 분류한다. Chat으로 분류된 뒤 모델이 mutation tool을 시도하면 Runtime이 `wanted_mutation` 신호를 남겨 work 전환을 제안하는 self-heal도 있다.

이 구조는 싸고 단순하지만, 실제 사용에서 더 어려운 문제는 단순 라우팅보다 **사용자 의도를 정확히 구조화하는 것**이다.

사용자는 보통 다음처럼 말한다.

> 모바일 원격제어가 아직 끊겨. 프론트와 백엔드를 둘 다 보고 근본적으로 고쳐. 기존 터치 입력은 깨지면 안 돼.

이 한 문장에는 이미 여러 정보가 들어 있다.

- 최종 목표
- 조사 범위
- 보존해야 할 기존 동작
- 암묵적인 회귀 방지 요구
- 복잡도
- 독립 조사 가능성

현재는 Planner/Developer가 실행 단계에서 이 의미를 다시 해석한다. 이 때문에 역할마다 같은 자연어를 반복 해석하고, 긴 프롬프트가 필요하며, 향후 병렬 Worker가 생기면 task decomposition의 기준도 불안정해진다.

따라서 사용자 자연어와 Agent Runtime 사이에 작은 의미 계약을 둔다.

```text
Natural Language
      ↓
Intent Interpreter
      ↓
FORGE Task IR
      ↓
Chat / Planner / Developer / Workers
      ↓
Acceptance Gates / Verification
```

핵심은 Interpreter를 또 하나의 Planner로 만드는 것이 아니다.

> **Interpreter는 무엇을 원하는지 정규화하고, Planner는 어떻게 할지 설계한다.**

---

## 2. 제품 목표

FORGE가 사용자의 짧고 자연스러운 요청을 더 잘 이해하게 만든다.

장기적으로 다음과 같은 사용 경험을 목표로 한다.

```text
사용자:
"에이전트 화면 아직 설정 페이지 같아. 캐릭터 선택 화면처럼 더 살아 있게 만들어.
기존 FORGE 디자인은 유지하고 실제 브라우저로 확인해."

Interpreter:
- intent: code_change
- goal: Agent Crew를 캐릭터 선택 화면처럼 개선
- requirements:
  - 기존 FORGE 디자인 언어 유지
  - 실제 browser에서 검증
- constraints:
  - Runtime 동작 변경 금지
- complexity: complex

Planner / Developer:
실제 구현 방법 결정
```

현재 사람이 긴 구현 프롬프트로 수동 보완하는 일부를 Harness 내부로 흡수하는 것이 목적이다.

---

## 3. 핵심 불변식

### 3.1 원문이 최종 의미 authority다

Task IR은 사용자 요청의 **파생 표현**이지 원문을 대체하지 않는다.

```text
User message = authoritative intent
Task IR      = normalized derived view
```

IR과 원문이 충돌하면 원문이 이긴다.

### 3.2 Interpreter는 새로운 요구를 발명하지 않는다

입력에 없는 다음 내용을 임의로 추가하면 안 된다.

- 새로운 기능
- 새로운 비목표
- 특정 아키텍처
- 특정 라이브러리
- 구현 방식
- 성능 수치
- 사용자가 요구하지 않은 scope 확대

불확실하면 `unknown` 또는 `clarification_required`로 남긴다.

### 3.3 Interpreter는 completion authority가 아니다

Interpreter가 만드는 것은 의미 구조다.

다음은 여전히 process-owned다.

- Acceptance Gate 실행
- test/build/browser evidence
- verification result
- completed / completed_unverified / verification_failed

### 3.4 Interpreter는 구현하지 않는다

파일 수정, bash, git, test 실행을 하지 않는다.

### 3.5 Interpreter 실패가 Runtime 전체 실패가 되어서는 안 된다

JSON parse 실패, timeout, provider 오류가 나면 기존 Triage/Runtime 경로로 fallback한다.

---

## 4. 역할 경계

### Interpreter가 결정/추출할 수 있는 것

- `intent`: chat / code_change / investigate / explain 등
- normalized goal
- 명시적 requirements
- 명시적 constraints / non-goals
- clarification 필요 여부
- 대략적인 complexity
- read-only 조사로 분리 가능한 subdomain 힌트
- 병렬화 가능성의 **힌트**

### Interpreter가 결정하지 않는 것

- 어느 함수에 어떤 코드를 쓸지
- 어떤 아키텍처가 정답인지
- 어떤 dependency를 추가할지
- 실제 테스트 명령
- Acceptance Gate command
- 최종 PASS/FAIL
- merge 전략
- commit/push 여부

역할 분리:

```text
Interpreter → WHAT
Planner     → HOW
Developer   → BUILD / REPAIR
Reviewer    → INDEPENDENT REVIEW
Harness     → VERIFY / COMPLETE
```

---

## 5. FORGE Task IR

초기 버전은 작고 안정적인 schema로 시작한다.

개념 예시:

```json
{
  "version": 1,
  "intent": "code_change",
  "goal": "모바일 원격제어 프레임 끊김 원인을 찾아 개선한다",
  "requirements": [
    "frontend와 backend 경로를 모두 확인한다",
    "기존 터치 입력 기능을 유지한다"
  ],
  "constraints": [
    "기존 원격 입력 동작을 회귀시키지 않는다"
  ],
  "complexity": "complex",
  "clarification_required": false,
  "clarification_question": "",
  "parallelizable_hint": true,
  "subdomains": [
    {
      "goal": "frontend polling/render 경로 조사",
      "mutation": false,
      "independent_hint": true
    },
    {
      "goal": "backend capture/response latency 조사",
      "mutation": false,
      "independent_hint": true
    }
  ]
}
```

초기 schema는 자주 바꾸지 않는다. 필요성이 실측되기 전에는 필드를 늘리지 않는다.

### 보존해야 할 원문

Task IR을 저장하더라도 실제 downstream context에는 원문을 함께 유지한다.

```text
[Original User Request]
...

[Interpreter Task IR]
...
```

모델이 IR만 보고 사용자의 뉘앙스를 잃지 않게 한다.

---

## 6. Requirement와 Acceptance Gate의 관계

Interpreter는 요구사항을 자연어 수준으로 정리한다.

```text
User
 ↓
Interpreter
 ↓
requirements[]
 ↓
Developer
 ↓
Executable Acceptance Gates
 ↓
Process Verification
```

예:

Interpreter:

```text
"기존 터치 입력 기능을 유지한다"
```

Developer/Harness:

```text
실제로 터치 입력 동작을 검증할 수 있는 gate/command/evidence
```

Interpreter가 verification command까지 만들게 하지 않는다. 의미 추출과 시험 설계를 분리해야 self-grading 위험이 커지지 않는다.

---

## 7. 모델 정책

초기에는 별도 비싼 모델을 상시 사용하지 않는다.

권장:

```text
Flash
+ constrained structured output
+ 작은 system prompt
+ representative few-shot
+ deterministic schema validation
```

원칙:

- no/low thinking부터 실험
- 출력은 JSON schema 강제
- parse/schema 실패 → fallback
- Interpreter 때문에 기본적으로 Pro를 호출하지 않음

향후 실제 ambiguity benchmark에서 가치가 확인될 때만 bounded Pro escalation을 검토한다.

모델이 출력하는 `confidence`가 필요하더라도 단독 라우팅 authority로 쓰지 않는다. 자기신뢰 점수는 calibration되지 않을 수 있으므로 deterministic signal과 실제 downstream 성공률로 평가한다.

---

## 8. 현재 Triage와의 통합

기존 Triage를 바로 삭제하지 않는다.

### Phase I0 — Shadow Interpreter

실제 routing에는 영향을 주지 않고 Task IR만 생성·기록한다.

```text
User Request
 ├→ 기존 Triage → 실제 Runtime
 └→ Interpreter → Task IR telemetry only
```

목적:

- latency
- token cost
- route agreement
- requirement extraction quality
- hallucinated requirement
- clarification quality

를 실제 사용에서 측정한다.

이 단계가 가장 중요하다. 먼저 의미 해석 품질을 증명한다.

### Phase I1 — Routing 통합

Shadow 데이터가 충분히 안정적이면 `intent`를 현재 chat/work routing에 사용한다.

기존 room mode는 유지한다.

- `chat`: Interpreter/Triage 없이 명시적으로 Chat
- `work`: Interpreter가 의미 정규화는 할 수 있지만 route는 Work 고정
- `auto`: Interpreter가 route + Task IR 생성

명시적인 사용자의 room mode가 Interpreter보다 우선한다.

### Phase I2 — Planner / Developer에 Task IR 주입

원문과 함께 validated Task IR을 전달한다.

효과를 비교한다.

- requirement 누락 감소
- 사용자 재질문 감소
- gate semantic coverage
- verified success rate
- prompt 길이
- 비용

### Phase I3 — Parallel Worker 준비

`subdomains`와 `parallelizable_hint`는 바로 Worker를 spawn하는 명령이 아니다.

Coordinator가 deterministic safety rule을 추가로 통과시킨 뒤에만 향후 read-only fresh worker에 사용한다.

---

## 9. 병렬 멀티에이전트와의 관계

Interpreter는 병렬 Agent보다 먼저 구축할 가치가 있다.

병렬화의 어려운 문제 중 하나는 "무엇을 독립적으로 나눌 수 있는가"이기 때문이다.

```text
사용자 자연어
      ↓
Interpreter
      ↓
Task IR
      ↓
독립 subdomain 후보
   ↙          ↘
Read-only A  Read-only B
   ↘          ↙
      Findings
         ↓
      Developer
```

단 Interpreter의 `parallelizable_hint=true`만으로 병렬 실행하지 않는다.

초기 병렬화는 다음 조건을 별도 확인해야 한다.

- read-only
- 파일 mutation 없음
- 서로 결과 의존성이 낮음
- worker count 상한
- worker token/time budget

즉 Task IR은 향후 parallel orchestration의 입력이지 orchestration 자체가 아니다.

---

## 10. Clarification 정책

Interpreter의 중요한 역할 중 하나는 **쓸데없는 질문을 줄이면서 정말 필요한 질문은 놓치지 않는 것**이다.

질문해야 하는 예:

- 두 해석이 결과를 크게 다르게 만듦
- destructive action 범위가 불명확
- 필수 target/workspace가 없음
- 사용자가 선택해야 하는 제품 정책

질문하면 안 되는 예:

- source를 읽으면 알 수 있음
- 기존 project convention으로 결정 가능
- harmless implementation detail
- 테스트로 확인할 수 있음

Interpreter는 질문을 생성할 수 있지만 실제 사용자 질문 여부는 Runtime policy가 최종 결정해도 된다.

---

## 11. Context / 비용 원칙

Interpreter가 새로운 context 폭주의 원인이 되면 안 된다.

입력:

- 현재 user turn
- 필요한 최소 최근 context
- room mode
- 선택적으로 짧은 workspace metadata

금지:

- 전체 conversation 재전송
- 전체 repository tree
- ROOM_MEMORY 전체를 무조건 복사
- tool history
- 대형 file content

Task IR의 목적은 downstream context를 더 명확하게 만드는 것이지, 앞단에 또 하나의 거대한 reasoning phase를 추가하는 것이 아니다.

---

## 12. Persistence / Observability

초기에는 새 DB table이 반드시 필요하지 않다.

가능한 최소 형태:

- eventlog에 interpreter result 기록
- session/run telemetry에 version/route/latency/token 정도 기록

실제 downstream 계약으로 사용하기 시작한 뒤 persistence 필요성을 재평가한다.

관측 이벤트 예:

```text
interpreter_start
interpreter_result
interpreter_fallback
interpreter_clarification
```

민감한 user text를 중복 저장하지 않도록 기존 history/event 정책과 맞춘다.

---

## 13. 평가 방법

Interpreter는 "그럴듯한 JSON"을 만드는 것으로 성공 판정하지 않는다.

### Offline fixture

자연어 요청 fixture를 만든다.

분류:

- pure chat
- simple code change
- complex code change
- investigate-only
- ambiguous request
- explicit constraint
- explicit non-goal
- multi-requirement
- scope-sensitive request
- parallelizable read-only investigation
- non-parallelizable dependent task

각 fixture에 최소 expected contract를 둔다.

예:

```text
route correctness
required requirement 포함
금지된 hallucinated requirement 없음
clarification expected 여부
```

### Dogfooding metrics

중요 지표:

1. route accuracy
2. requirement recall
3. hallucinated requirement rate
4. unnecessary clarification rate
5. missed clarification rate
6. downstream verified success rate
7. false completion rate
8. human intervention
9. Interpreter latency
10. Interpreter cost
11. 전체 cost per verified task

최종 판단은 Interpreter 자체 정확도보다 **전체 FORGE 성공률과 사용자 개입이 좋아지는가**로 한다.

---

## 14. Failure / Fallback

다음 경우 기존 경로로 안전하게 돌아간다.

- timeout
- invalid JSON
- schema mismatch
- 빈 goal
- unsupported IR version
- provider error

```text
Interpreter failure
→ original user request 보존
→ current Triage/room mode path
```

Interpreter 장애가 사용자의 작업을 막으면 안 된다.

---

## 15. Security / Trust Boundary

Interpreter는 실행 권한이 없다.

- filesystem mutation 없음
- shell 없음
- git 없음
- credential 없음
- approval 변경 없음
- sandbox policy 변경 없음

IR 안의 `constraints`나 `subdomains`는 instruction provenance를 가진 파생 데이터로 취급하고, system policy보다 높은 권한을 갖지 않는다.

외부/첨부 콘텐츠가 들어간 요청에서도 prompt injection 문자열을 새로운 system instruction으로 승격하지 않는다.

---

## 16. UI / Agent Crew

현재 Agent Crew에서 Triage는 내부 시스템으로 표현된다.

Interpreter가 실제 Runtime 역할로 승격되면 다음처럼 설명할 수 있다.

```text
Interpreter
"당신의 말을 FORGE가 실행할 수 있는 목표로 해석합니다."

Model      Flash
Mutation   None
Context    Minimal
Output     Task IR
```

그러나 I0 Shadow 단계에서는 아직 사용자-facing Core Agent로 승격시키지 않는다. 실제 효용이 확인된 뒤 Agent Crew의 `내부 시스템` 영역에서 Triage를 Interpreter로 교체/확장한다.

---

## 17. 구현하지 않을 것

초기 단계에서 하지 않는다.

- Interpreter가 직접 코드 설계
- Interpreter가 Acceptance Gate command 작성
- Interpreter가 tool 실행
- Interpreter가 completion 판정
- giant ontology / knowledge graph
- vector DB
- 별도 multi-agent debate
- Interpreter끼리 voting
- 항상 Pro 사용
- 사용자 원문을 IR로 대체
- IR 한 번의 판단만으로 parallel mutation worker spawn

---

## 18. 단계별 완료 기준

### I0 — Shadow

- 현재 Triage 동작 회귀 없음
- structured Task IR 생성
- schema validation
- 실패 fallback
- telemetry
- fixture test
- 실제 routing에 영향 없음

### I1 — Routing

- auto mode에서 route accuracy가 기존보다 유지/향상
- explicit room mode 우선
- mutation misroute self-heal 유지
- latency/cost 허용 범위

### I2 — Runtime Contract

- Planner/Developer가 원문 + Task IR 사용
- requirement/gate 누락 감소
- verified success rate 후퇴 없음
- human intervention 감소 또는 유지

### I3 — Worker Input

- read-only 독립 subdomain 후보 생성 품질 검증
- parallel worker는 별도 proposal/benchmark gate 후 연결

---

## 19. 성공 기준

이 기능의 성공은 "Triage가 더 똑똑해 보인다"가 아니다.

다음 경험이 실제로 좋아져야 한다.

```text
짧은 사용자 요청
→ 정확한 의도 이해
→ 불필요한 질문 없음
→ 요구사항 누락 없음
→ 적절한 Agent 경로
→ 실제 구현/검증 성공
```

특히 장기적으로는 사람이 FORGE를 쓰기 위해 만드는 거대한 구현 프롬프트가 짧아져야 한다.

> **FORGE가 성숙할수록 사용자는 제품 목표와 제약만 말하고, Harness가 이를 실행 가능한 의미 구조로 바꿔야 한다.**

---

## 20. 최종 방향

현재 Triage:

```text
Natural Language
→ CHAT / WORK
```

목표 Interpreter:

```text
Natural Language
      ↓
Semantic Interpretation
      ↓
FORGE Task IR
      ↓
Routing / Planning / Execution / Workers
      ↓
Deterministic Verification
```

이 계층은 FORGE를 더 많은 Agent로 복잡하게 만드는 기능이 아니라, **사용자 언어와 Harness 사이 계약을 명확하게 만드는 기능**이다.

병렬 멀티에이전트보다 먼저 작게 실험할 가치가 있으며, 첫 구현은 반드시 `Shadow + Flash + Structured Output + Fallback`으로 시작한다.
