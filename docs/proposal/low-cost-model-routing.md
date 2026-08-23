# FORGE 저비용 멀티모델 라우팅 제안

> 상태: Proposal / Experimental
> 작성 기준: 2026-08-23
> 북극성: **모델 단가가 아니라 `cost_per_successful_task`를 최소화한다.**

## 1. 배경

FORGE의 경쟁력은 특정 LLM에 종속되는 데 있지 않다. 핵심은 저렴한 모델의 불확실성을 Developer Harness의 탐색·실행·검증·수리·복구·계측으로 통제하여 실제 작업을 끝내는 것이다.

현재 DeepSeek V4 Flash는 매우 낮은 캐시 단가와 Agent/tool calling 성능 때문에 좋은 기본값이지만, 2026년 8월 기준으로 더 싼 유료 모델과 무료 preview endpoint가 등장하고 있다. 따라서 FORGE는 특정 모델을 고정하는 대신 **동일한 Developer runtime 위에서 모델을 교체·비교·승격·fallback할 수 있는 비용 최적화 계층**을 갖추는 편이 제품 방향에 맞다.

이 제안의 목표는 새로운 Agent를 추가하는 것이 아니다.

```text
Developer
  ├─ Ox Alpha
  ├─ Ling 3.0 Flash
  ├─ Qwen3.7 Flash
  ├─ DeepSeek V4 Flash
  └─ DeepSeek V4 Pro
```

Agent는 계속 하나의 Developer이며, 모델만 task/runtime 상태에 따라 선택한다.

---

## 2. 가격 스냅샷

아래 가격은 **2026-08-23 시점의 API/OpenRouter 공개 가격 스냅샷**이다. 무료 preview, 할인, provider routing, 가격 정책은 언제든 바뀔 수 있으므로 런타임 상수로 영구 가정하지 않는다.

| 모델 | Input / 1M | Cache Read / 1M | Output / 1M | Context | 비고 |
|---|---:|---:|---:|---:|---|
| Ox Alpha | $0 | - | $0 | ~1.05M | Stealth preview, 무료 |
| Ling 3.0 Flash `:free` | $0 | - | $0 | 262K | 무료 endpoint, rate limit 가능 |
| Ling 3.0 Flash | $0.021 | $0.0042 | $0.063 | 262K | tool calling 지원 |
| Qwen3.7 Flash | $0.03 | provider 정책 | $0.13 | 1M | multimodal/agent 후보 |
| DeepSeek V4 Flash | $0.14 miss | $0.0028 hit | $0.28 | 1M | 현재 기준선 |
| DeepSeek V4 Pro | $0.435 miss | $0.003625 hit | $0.87 | 1M | escalation 후보 |

### 핵심 해석

Raw input/output 가격만 보면 Ling/Qwen/Ox가 더 싸다. 그러나 FORGE처럼 같은 stable prefix와 task context를 반복 재사용하는 장기 Agent loop에서는 **DeepSeek의 매우 낮은 cache-hit input 가격**이 역전 요인이 될 수 있다.

따라서 다음과 같은 단순 비교는 금지한다.

```text
input 단가가 더 싸다
→ 기본 모델로 교체
```

대신 반드시 다음으로 판단한다.

```text
(successful task를 끝내기까지 발생한 모든 호출 비용)
--------------------------------------------------
                    성공 작업 수
```

즉 `cost_per_success`가 최종 기준이다.

---

## 3. 전략: 모델 시장을 실행 자원처럼 사용

FORGE는 모델을 제품 정체성으로 보지 않고 **교체 가능한 실행 자원**으로 취급한다.

무료/할인 모델이 등장하면 Harness에 넣고 실측한다. 품질이 충분하면 적극 사용하고, 종료되거나 가격이 오르면 제거하거나 다른 모델로 교체한다.

```text
Model Market
   ↓
Capability + Price Snapshot
   ↓
FORGE Eval
   ↓
Routing Policy
   ↓
Developer Runtime
```

이 구조를 통해 FORGE는 특정 provider의 가격 정책 변화에 덜 민감해진다.

---

## 4. 1차 후보군

### 4.1 Ox Alpha — 무료 버닝 후보

현재 무료 preview이므로 공개 OSS·개인 비민감 프로젝트에서 적극 실험할 가치가 있다.

장점:
- 현재 input/output 무료
- 약 1M context
- coding / sustained agentic work 지향
- OpenAI-compatible OpenRouter 경로

리스크:
- stealth provider
- preview 종료/가격 변경 가능
- provider가 prompt/completion을 retain하는 정책이 있으므로 민감 코드 사용 금지
- 무료 endpoint 특성상 rate limit/availability 변동 가능

정책:

```text
PUBLIC / PERSONAL_NON_SENSITIVE
→ 사용 가능

CORPORATE / SECRET / CREDENTIAL / PRIVATE_SENSITIVE
→ 사용 금지
```

Ox Alpha는 production default가 아니라 **opportunistic experimental compute**로 취급한다.

### 4.2 Ling 3.0 Flash — 지속 가능한 초저가 후보

무료 endpoint가 사라져도 paid 가격이 매우 낮아 가장 중요한 장기 후보 중 하나다.

특히 Agent inference와 token efficiency를 목표로 설계되었고 tool calling을 지원하므로 FORGE Developer와 직접 A/B할 가치가 높다.

우선 검증 항목:
- tool-call 정확도
- edit/test/repair 장기 loop 안정성
- repeated call 비율
- structured output 제약
- context 262K가 실제 repo task에 충분한지
- paid/free endpoint 품질 차이

### 4.3 Qwen3.7 Flash — 1M context 저가 후보

Ling보다 단가는 약간 높지만 1M context와 multimodal 특성이 강점이다.

특히 향후 Developer가 Vision을 별도 Agent가 아니라 capability로 흡수한다면 텍스트/이미지 통합 라우팅 후보로 평가할 가치가 있다.

### 4.4 DeepSeek V4 Flash — 기준선

DeepSeek는 당장 제거 대상이 아니다.

강점:
- 검증된 FORGE integration
- 1M context
- thinking / non-thinking
- tool calling
- 매우 낮은 cache-hit 가격
- 높은 concurrency

새 후보들은 DeepSeek보다 싸다는 이유가 아니라 **동일 성공률에서 더 낮은 CPS를 만들 때만** 기본 route를 가져간다.

### 4.5 DeepSeek V4 Pro — 고난도 escalation 기준선

Pro는 모든 작업에 쓰지 않는다. Flash/저가 모델이 반복 실패하거나 고위험·고복잡도 task에서만 승격하는 현재 철학을 유지한다.

---

## 5. 목표 아키텍처

### 5.1 Agent 구조는 유지

```text
User
 ↓
Triage
 ├─ CHAT → Chat
 └─ CODE → Developer
              ↓
         Model Router
              ↓
 Plan → Execute → Verify → Repair
```

새 모델마다 `OxAgent`, `LingAgent`, `QwenAgent`를 만들지 않는다.

### 5.2 ModelProfile

필요하다면 최소한의 capability metadata를 둔다.

```python
ModelProfile(
    provider="openrouter",
    model="inclusionai/ling-3.0-flash",
    tools=True,
    vision=False,
    thinking=False,
    context_window=262_144,
    privacy_class="external",
    cost_class="ultra_low",
)
```

목표는 거대한 provider framework가 아니라 **동일 Developer loop에서 안전하게 교체 가능한 최소 계약**이다.

### 5.3 Provider abstraction

개념적으로 다음만 분리하면 충분하다.

```text
Developer Runtime
      ↓
Model Client / Provider Adapter
      ├─ DeepSeek
      └─ OpenRouter
             ├─ Ox Alpha
             ├─ Ling
             └─ Qwen
```

OpenAI-compatible endpoint의 공통 부분은 재사용한다.

---

## 6. 초기 Routing 제안

벤치마크 전에는 복잡한 AI router를 만들지 않는다. 설정 기반 또는 deterministic policy로 시작한다.

### Experimental policy

```text
비민감 공개/개인 task
  ↓
무료 모델 사용 가능?
  ├─ YES → Ox Alpha 또는 Ling :free
  └─ NO  → paid candidate

candidate 반복 실패 / capability mismatch
  ↓
DeepSeek V4 Flash

Flash 반복 실패 / high-risk high-complexity
  ↓
DeepSeek V4 Pro
```

단, 이 순서는 **가설**이며 benchmark 결과로 바뀌어야 한다.

무료 모델을 항상 먼저 호출하는 것이 최적이라는 보장은 없다. 무료 모델이 자주 실패해 재시도와 context를 소비하면 유료 Flash 한 번보다 시간·자원 비용이 더 커질 수 있다.

---

## 7. 가장 중요한 비교

다음 세 패턴을 동일 task에서 비교한다.

### A. Current baseline

```text
DeepSeek Flash
→ 성공
```

### B. Cheap-first

```text
Ling/Ox
→ 성공
```

### C. Cheap failure chain

```text
Ling/Ox
→ 실패
→ repair
→ 실패
→ DeepSeek Flash
→ 성공
```

### D. Strong-first

```text
DeepSeek Pro 또는 강한 후보
→ 1-pass 성공
```

FORGE는 B가 항상 최고라고 가정하지 않는다. C의 총비용이 A보다 높다면 cheap-first 정책은 실패다. 반대로 고난도 task에서 강한 모델 한 번이 여러 저가 호출보다 싸다면 strong-first route가 정답일 수 있다.

---

## 8. Benchmark 설계

기존 deterministic R0 harness와 실제 repo task set을 최대한 재사용한다.

### Task class

- SIMPLE: 단일 파일 수정
- MEDIUM: 여러 파일 탐색 + 수정 + 테스트
- HARD: repo-level 구조 이해 및 기능 구현
- REPAIR: 실패 로그 분석 후 재수정
- LONG: read/grep/edit/bash/test가 반복되는 장기 task
- VISUAL: 이미지/스크린샷 기반 task (지원 모델에 한함)

### 반복

모델당 task당 최소 3회, 가능하면 5회 수행한다.

### Primary metrics

```text
success_rate
cost_per_success
verified_completion_rate
```

### Secondary metrics

```text
elapsed_p50 / p95
first_pass_success_rate
repair_success_rate
model_calls_per_success
tool_calls_per_success
prompt_tokens_per_success
completion_tokens_per_success
cached_tokens_per_success
cache_hit_rate
repeated_tool_calls
human_intervention
```

### 무료 모델용 normalized metrics

무료 모델은 `$0`이므로 가격만 비교하면 무조건 승리한다. 따라서 다음을 별도 기록한다.

```text
tokens_per_success
calls_per_success
elapsed_per_success
first_pass_success
repair_count
availability / rate-limit failures
```

가격이 생긴 뒤에도 과거 raw usage로 CPS를 재계산할 수 있도록 usage telemetry를 보존한다.

---

## 9. Promotion Gate

새 모델은 다음 조건을 통과해야 기본 route 후보가 된다.

```text
verified_success_rate >= baseline - 허용 오차
AND
cost_per_success < baseline
AND
unsafe_behavior_rate <= baseline
AND
operational_failure_rate 허용 범위
```

무료 모델의 경우 `cost_per_success = 0`만으로 승격시키지 않는다. normalized efficiency와 availability를 함께 본다.

판정 상태:

```text
REJECT
EXPERIMENTAL
ROUTING_ONLY
DEFAULT_CANDIDATE
```

초기 Ox Alpha는 `EXPERIMENTAL`, Ling/Qwen은 `EXPERIMENTAL` 또는 benchmark 후 `ROUTING_ONLY`가 적절하다.

---

## 10. Privacy / Security Policy

가격 최적화가 보안 경계를 넘으면 안 된다.

Task에 다음 정보가 포함되면 stealth/free third-party route를 차단한다.

- API keys / tokens / credentials
- 회사 내부 소스
- 개인정보
- 운영 DB dump
- private certificates
- 비공개 인프라 정보

장기적으로 task마다 최소 privacy class를 둔다.

```text
PUBLIC
PERSONAL
PRIVATE
CORPORATE
SECRET
```

ModelProfile의 허용 privacy class와 비교하여 router가 provider를 제한한다.

이 기능이 구현되기 전에는 Ox Alpha 같은 stealth provider는 opt-in으로만 사용한다.

---

## 11. 무료 Endpoint 정책

무료 endpoint는 정상 provider와 다르게 취급해야 한다.

필요 정책:
- rate-limit 발생 시 bounded fallback
- provider unavailable 시 즉시 다른 모델로 전환
- 동일 request 무한 retry 금지
- 무료 종료/모델 삭제를 runtime failure로 취급하지 않고 capability refresh 대상으로 처리
- production SLA에 포함하지 않음

```text
FREE_ROUTE_FAILURE
→ retry 0~1회
→ paid stable route fallback
```

무료라는 이유로 전체 task latency를 폭주시켜서는 안 된다.

---

## 12. 가격 데이터 관리

현재 `MODEL_PRICING` 같은 정적 테이블은 benchmark 재현에는 유용하지만 시장 가격과 쉽게 어긋난다.

단계적으로 다음을 고려한다.

### P0

수동 스냅샷 + `last_verified_at` 기록.

### P1

provider/model별 가격을 config로 분리.

### P2

OpenRouter 등 pricing endpoint를 이용한 optional refresh.

단, 런타임 routing이 외부 가격 API 장애에 종속되면 안 된다. 마지막 검증값을 사용하고 freshness만 telemetry에 남긴다.

---

## 13. 구현 단계

### Phase 0 — Benchmark only

- OpenRouter API key/config 추가
- Ox/Ling/Qwen model slug를 실험 설정으로 추가
- 기존 Developer loop 그대로 사용
- 모델별 raw usage/latency/success 측정
- production routing 변경 없음

### Phase 1 — Optional model selection

- 세션/실행 요청에서 experimental model 선택 가능
- UI/Admin에서 model과 provider 식별
- telemetry에서 role이 아니라 model/provider로 비용 분해

### Phase 2 — Deterministic routing

- privacy class
- free endpoint eligibility
- repeated failure
- context length
- vision/tool capability

정도만 규칙 기반으로 라우팅한다.

### Phase 3 — Cost-aware promotion

충분한 실제 실행 데이터가 쌓이면 task class별 CPS 기준으로 기본 모델을 결정한다.

```text
SIMPLE → cheapest verified winner
MEDIUM → best CPS winner
HARD → best CPS winner
VISUAL → vision-capable best CPS winner
FAILURE → best repair CPS winner
```

LLM이 다른 LLM을 고르는 별도 Router Agent는 도입하지 않는다. routing 자체에 추가 inference 비용을 만들지 않는다.

---

## 14. 성공 조건

이 제안의 성공은 "지원 모델 수"가 늘어나는 것이 아니다.

성공 조건은 다음과 같다.

1. DeepSeek 단일 의존도를 낮춘다.
2. 무료/초저가 모델을 안전하게 활용한다.
3. 동일 성공률에서 CPS를 낮춘다.
4. 무료 preview 종료에도 runtime이 흔들리지 않는다.
5. Agent 수와 orchestration complexity는 늘리지 않는다.
6. 가격/성능 변화에 따라 모델을 교체할 수 있다.

---

## 15. 하지 말 것

- 모델마다 Agent class 추가
- Multi-Agent 구조 복구
- Planner/Reviewer/Debugger 복구
- 무료 모델을 production default로 즉시 전환
- 모델 벤치마크 점수만 보고 승격
- privacy policy 없이 stealth provider로 민감 코드 전송
- free endpoint retry 무한 루프
- 가격만 최적화하고 성공률/verified completion 악화 허용

---

## 16. 최종 제안

FORGE는 "DeepSeek 기반 코딩 Agent"보다 다음 방향이 더 강하다.

> **가장 경제적인 모델을 그때그때 활용하되, 품질은 FORGE Harness가 보장하는 self-hosted execution engine.**

DeepSeek는 현재 매우 강한 기준선으로 유지한다. 동시에 Ox Alpha의 무료 preview를 적극 활용하고, Ling 3.0 Flash와 Qwen3.7 Flash를 지속 가능한 초저가 후보로 실측한다.

권장 우선순위:

```text
P0  Ox Alpha / Ling / Qwen 동일 Harness A/B
P1  provider/model telemetry 정규화
P1  privacy-aware experimental routing
P2  deterministic cheap-first / failure fallback 실험
P2  task-class별 CPS promotion
```

**다음 행동은 라우터를 먼저 만드는 것이 아니라 동일 Developer Harness에서 후보 모델의 실제 CPS 데이터를 확보하는 것이다.**

---

## 참고 가격 출처

- DeepSeek API Docs — Models & Pricing
- OpenRouter — Ox Alpha
- OpenRouter — Ling 3.0 Flash / Ling 3.0 Flash Free
- OpenRouter — Qwen3.7 Flash

가격은 2026-08-23 스냅샷이며 실제 구현/의사결정 전 최신 값을 다시 확인한다.
