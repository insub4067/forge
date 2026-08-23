# 온프레미스 LLM 추론 최적화 및 Speculative Decoding 제안

> 상태: Proposal
> 목표: FORGE를 외부 DeepSeek API뿐 아니라 사내/폐쇄망 LLM에서도 높은 품질과 처리량으로 동작하는 모델 독립적 Harness로 확장한다.

## 1. 핵심 방향

FORGE의 목표는 가장 저렴하거나 가장 빠른 모델을 사용하는 것이 아니다.

> **효율적인 모델을 Harness의 실행·검증·수리·복구 프로세스와 결합해 verified task를 가장 효율적으로 완료하는 것**이 목표다.

온프레미스에서는 API 토큰 비용보다 GPU 자원, 처리량, 지연시간, 전력, 동시성이 중요한 비용이 된다.

따라서 최상위 KPI는 단순 `tokens/sec`가 아니라 다음과 같이 정의한다.

```text
verified_tasks_per_hour
verified_success_rate
elapsed_per_verified_task
model_calls_per_verified_task
energy_or_compute_per_verified_task
```

## 2. 배경

최근 공개된 Ling 3.0 Flash + DSpark 사례는 speculative decoding이 agent workload의 추론 속도를 크게 개선할 가능성을 보여준다.

구조는 다음과 같다.

```text
Small Draft Model
        ↓
여러 다음 token 후보 생성
        ↓
Target Model
        ↓
후보를 한 번에 검증
        ↓
accept / correction
```

큰 모델이 모든 token을 순차 생성하는 대신 작은 draft model이 앞서 생성하고 target model이 여러 token을 한 번에 검증한다.

중요한 점은 특정 Ling/DSpark 구현을 FORGE에 종속시키는 것이 아니다.

FORGE는 speculative decoding을 포함한 여러 serving strategy를 동일 benchmark에서 비교할 수 있어야 한다.

## 3. FORGE와의 결합

FORGE는 이미 inference 바깥의 효율을 개선하고 있다.

```text
Context Engineering
├─ selective retrieval
├─ find_symbol
├─ large-file symbol map
├─ tool result compression
├─ deferred tool result access
└─ context telemetry

Quality Harness
├─ deterministic verification
├─ repair
├─ bounded escalation
├─ durable resume
└─ benchmark / RSI gate
```

Speculative decoding은 이 구조와 경쟁하지 않는다.

```text
FORGE Harness Optimization
→ 모델에 더 적고 좋은 정보를 전달

Inference Optimization
→ 전달된 요청을 더 빠르게 생성
```

두 최적화는 서로 다른 병목을 줄인다.

## 4. 모델 Provider 추상화

DeepSeek 전용 구조에서 벗어나 OpenAI-compatible endpoint를 일급 provider로 지원한다.

예시:

```text
Provider
├─ DeepSeek API
├─ Internal OpenAI-compatible API
├─ vLLM
├─ SGLang
├─ MLX server
└─ future providers
```

설정 예:

```env
LLM_PROVIDER=internal
LLM_BASE_URL=https://llm.internal/v1
LLM_MODEL=internal-coder
LLM_API_KEY=...
```

Provider 변경이 Agent/Verification/Skill 코드에 영향을 주지 않게 한다.

## 5. 사내 배포 아키텍처

FORGE 자체는 중앙 SaaS가 아니라 사용자 PC에서 동작하는 1인용 local agent runtime을 유지한다.

```text
Developer Windows PC
└─ FORGE (WSL2 또는 향후 Native Host)
   ├─ workspace
   ├─ git
   ├─ build/test
   ├─ tools
   ├─ skills
   └─ verification
          ↓ internal network
      LLM Gateway
          ↓
      Inference Pool
```

소스 수정과 deterministic verification은 사용자 PC에서 수행한다.

중앙화되는 것은 모델 inference다.

## 6. Inference Pool

초기 구조:

```text
LLM Gateway
├─ Fast Pool
│   └─ 효율적인 coding/agent model replicas
│
└─ Strong Pool
    └─ 고성능 model / multi-node model
```

FORGE routing:

```text
Triage / ordinary development
→ Fast Pool

verification failure
→ repair

반복 실패 / 높은 불확실성
→ Strong Pool bounded escalation
```

큰 모델 하나를 모든 작업에 사용하는 방식은 피한다.

## 7. Speculative Decoding

Serving engine이 지원하는 경우 draft model을 선택적으로 사용한다.

```text
Request
  ↓
Draft Model
  ↓
Target Model Verification
  ↓
Response
```

FORGE는 speculative decoding 구현 자체를 Agent runtime에 넣지 않는다.

이 기능은 inference server 책임으로 둔다.

FORGE는 다음만 담당한다.

- serving configuration 식별
- benchmark metadata 기록
- 성능 비교
- regression detection

## 8. Inference Configuration Identity

단순 model name만 기록하면 안 된다.

하나의 inference configuration을 다음처럼 식별한다.

```text
InferenceConfig
- model
- model_revision
- serving_engine
- quantization
- context_limit
- draft_model
- speculative_enabled
- tensor_parallel
- hardware_profile
```

같은 모델이라도 serving configuration이 다르면 별개의 benchmark 대상이다.

## 9. Benchmark 확장

기존 deterministic benchmark를 inference benchmark로 확장한다.

비교 예:

| 구성 | Verified Success | Repair | tok/s | Task Time | Verified Tasks/h |
|---|---:|---:|---:|---:|---:|
| Model A baseline | 측정 | 측정 | 측정 | 측정 | 측정 |
| Model A speculative | 측정 | 측정 | 측정 | 측정 | 측정 |
| Model B | 측정 | 측정 | 측정 | 측정 | 측정 |

가장 중요한 규칙:

> `tokens/sec` 향상이 `verified success` 하락을 정당화하지 않는다.

## 10. 최상위 KPI: Verified Tasks / Hour

Agent Harness에서 raw token generation speed는 중간 지표다.

예:

```text
Model A
1000 tok/s
60% verified success
많은 repair

Model B
250 tok/s
95% verified success
적은 repair
```

Model A가 반드시 더 생산적인 것은 아니다.

따라서 다음을 계산한다.

```text
verified_tasks_per_hour = verified_completed_tasks / elapsed_hours
```

추가 지표:

```text
model_calls_per_verified_task
repair_calls_per_verified_task
escalations_per_verified_task
input_tokens_per_verified_task
output_tokens_per_verified_task
```

## 11. 온프레미스 비용 지표

외부 API에서는 `cost_per_success`가 중요하지만 온프레미스에서는 실제 API 청구가 없다.

대신 다음을 지원할 수 있다.

```text
GPU seconds / verified task
Watt-hours / verified task
GPU memory peak
queue wait time
throughput
```

초기 구현에서는 GPU seconds와 elapsed만 수집하고 전력 계측은 후순위로 둔다.

## 12. Context Engineering과 연결

최근 FORGE telemetry에서 tool result와 반복적인 file read가 큰 context 비용원으로 확인됐다.

온프레미스에서는 token 감소가 단순 비용 절감 이상의 의미를 가진다.

```text
적은 context
→ KV cache 감소
→ GPU memory 여유
→ latency 감소 가능
→ concurrency 증가
→ 동일 하드웨어로 더 많은 verified task 처리
```

따라서 다음 지표를 inference benchmark와 함께 본다.

- context tokens
- tool_raw_tokens
- tool_visible_tokens
- read_file count
- find_symbol count
- cache hit rate

## 13. Hardware Profile

Benchmark 결과에는 hardware profile을 반드시 연결한다.

예:

```text
HardwareProfile
- type: DGX Spark / Mac Studio / GPU Server
- accelerator
- memory
- node_count
- interconnect
- serving_engine
```

이를 통해 다음 질문에 수치로 답할 수 있다.

```text
Mac Studio 한 대가 FORGE 작업을 시간당 몇 개 처리하는가?
DGX Spark 두 대에서는 얼마인가?
Speculative decoding을 켜면 실제 verified throughput이 얼마나 증가하는가?
```

## 14. Windows / 폐쇄망

사용자 PC는 Windows + WSL2를 초기 표준으로 한다.

```text
Windows
└─ WSL2
   └─ FORGE
```

폐쇄망에서는 다음 외부 의존성을 점검한다.

- LLM API → 내부 endpoint
- Git → 내부 Git service
- npm/pip → 사내 package mirror
- web search → 비활성 또는 내부 search
- Web Push → 내부 알림 대체 검토

핵심 Harness는 인터넷 없이 동작할 수 있어야 한다.

## 15. 보안 경계

소스코드는 사용자 PC와 내부 LLM 네트워크 밖으로 나가지 않는 것을 기본으로 한다.

향후 외부 provider를 함께 지원할 경우 Data Egress Gate를 별도 설계한다.

```text
Context
 ↓
Classification
 ├─ Public → approved external provider 가능
 ├─ Internal → private/internal model
 └─ Sensitive → on-prem only
```

API key, credential, 개인정보, 내부 IP/DB 접속정보 등에 대한 secret detection/redaction도 별도 proposal 대상으로 둔다.

## 16. 단계별 구현

### Phase P0 — Internal Provider

- OpenAI-compatible base URL 지원
- model/provider configuration 분리
- 기존 DeepSeek 동작 regression 방지

### Phase P1 — Inference Metadata

- model revision
- serving engine
- quantization
- hardware profile
- speculative configuration 기록

### Phase P2 — Benchmark 확장

- verified_tasks_per_hour
- model_calls_per_verified_task
- repair/escalation count
- context/tool token metrics 결합

### Phase P3 — Speculative A/B

동일 target model에 대해:

```text
baseline serving
vs
speculative serving
```

고정 benchmark를 실행한다.

성공률 regression이 없을 때만 성능 개선으로 인정한다.

### Phase P4 — Fast / Strong Pool

- endpoint별 model tier
- bounded escalation
- queue/latency telemetry

### Phase P5 — Hardware Benchmark

- Mac Studio
- DGX Spark
- NVIDIA GPU server

등을 동일 FORGE benchmark로 비교한다.

## 17. Promotion Gate

Inference configuration도 RSI와 같은 철학으로 승격한다.

```text
verified_success_rate regression
→ REJECT

성공률 유지
→ verified_tasks_per_hour 비교

처리량 유사
→ resource efficiency 비교
```

작은 benchmark noise로 설정이 계속 바뀌지 않도록 minimum meaningful improvement 또는 반복 측정을 후속 도입한다.

## 18. 하지 않을 것

- 특정 Ling/DSpark 구현에 FORGE를 종속
- speculative decoding을 Agent runtime에서 직접 구현
- tok/s만 보고 모델 선정
- 큰 모델을 모든 작업에 강제
- 성공률을 희생해 throughput 향상
- benchmark 없이 quantization 변경
- benchmark 없이 context limit 축소
- 외부 API와 내부 LLM의 보안 경계를 동일하게 취급

## 19. 완료 기준

다음을 만족하면 1차 도입 완료로 본다.

1. FORGE가 DeepSeek와 내부 OpenAI-compatible endpoint를 설정만으로 전환할 수 있다.
2. inference configuration이 telemetry에 기록된다.
3. 동일 benchmark에서 baseline/speculative serving을 비교할 수 있다.
4. `verified_tasks_per_hour`를 계산할 수 있다.
5. success rate regression이 있는 빠른 configuration은 자동으로 우수하다고 평가하지 않는다.
6. context engineering 효과와 inference throughput을 함께 분석할 수 있다.
7. Windows + WSL2 + 내부 LLM endpoint 환경에서 핵심 Harness가 인터넷 없이 동작한다.

## 20. 최종 방향

FORGE의 장기 목표는 특정 모델의 wrapper가 아니다.

```text
Efficient Model
      +
Efficient Inference
      +
Context Engineering
      +
Execution Harness
      +
Deterministic Verification
      +
Repair / Escalation
      =
High Verified Throughput
```

외부 API 환경에서는 `cost_per_success`를 최적화하고, 온프레미스 환경에서는 `verified_tasks_per_hour`와 compute efficiency를 최적화한다.

모델과 하드웨어가 바뀌어도 FORGE가 동일한 benchmark와 품질 기준으로 가장 효율적인 실행 구성을 선택할 수 있게 만드는 것이 최종 목표다.
