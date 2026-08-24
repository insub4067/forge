# FORGE Proposal Index / Adoption Status

> Proposal은 당시의 설계 의도와 연구 기록이다. 현재 구현 판단은 코드와 `docs/core`, `docs/status`를 우선한다.

## 제품 원칙

FORGE는 단순 저비용 LLM wrapper가 아니다.

> **저렴한 모델의 불확실성을 Harness의 실행·검증·수리·복구·계측으로 통제해 품질을 보장한다.**

Proposal 채택 여부도 기능 수나 token 절감보다 success/verification 효과를 먼저 본다.

## 기각·보류 (재검토 트리거 전까지 다시 읽지 말 것)

아래는 2026-08-24 전체 재검토에서 "지금 착수 안 함"으로 결론난 항목이다. 각 재검토 트리거가
실제로 발생하기 전엔 본문을 다시 정독하지 않는다.

**기각 (재검토 안 함)**
- `tauri-desktop-host` — 현 "맥 직접 실행 + Cloudflare Access" 배포로 충분. Python backend 번들링 리스크가 크고 success-rate와 무관. 트리거: 다중 사용자 설치형 배포 수요.
- `home-camera-monitor` — 코딩 하네스와 무관한 optional 모듈. 프라이버시/보안 표면만 넓힌다(현 JPEG polling PoC 유지). 트리거: 홈 모니터를 별도 제품으로 만들기로 결정.
- `prime-agent` B(Restricted Tool Script) — 벤치 결과 기각(효과 없음). 코드 없음.
- `claude-code-cleanroom`의 task 상태머신·coordinator/worker 부분 — 현 올인원 Developer + process verification 구조와 상충. (같은 문서의 permission/steering 아이디어 일부는 이미 반영.) 트리거: 다중 worker 병렬 실행 도입.

**보류 (조건 충족 전 착수 금지)**
- `low-cost-model-routing` (Ling 3.0 Flash·Qwen 등 포함) — DeepSeek flash가 이미 cache 95%로 거의 공짜(6.1M tok/$0.26 실측). 무료 티어는 레이트리밋·프라이버시(비공개 코드 학습)·tool-call 신뢰성 리스크. 트리거: **21-task R0 벤치에서 후보 모델이 동등 success_rate + CPS 우위를 실증**할 때만 어댑터 착수.
- `web-search-tools` — 트리거: 벤치로 CPS 개선이 확인될 때.
- `live-screen-preview` WebRTC 고도화 — 현 JPEG 폴링으로 목적 달성. 트리거: 지연이 실사용 병목으로 확인될 때.
- `durable-worker-resume` D2(worker 프로세스 분리)·`forge-mcp-agent-runtime` remote transport/인증 — 단일 Mac 호스트 + stdio 배포에선 speculative. 트리거: 원격/분산 배포 또는 외부 위임 실수요.
- `forge-runtime-hardening-roadmap` P1~P6(ExecutionBackend·event replay·benchmark 라우터·병렬 Developer) — 단일 호스트에선 과설계. 트리거: 원격 실행 대상 또는 병렬 실행 수요.
- `onprem-inference-optimization` — 철학은 FORGE 원칙과 정합하나, 존재하지 않는 배포 환경(온프레미스 GPU·폐쇄망·vLLM/SGLang 서빙·DGX/Mac Studio)을 전제로 한 인프라라 지금은 speculative. P0(OpenAI 호환 provider 추상화)는 2026-08-24 Ling 실험으로 구현 가능성 실증됨(git dff74c0, 이후 제거) — 필요 시 재추가는 저비용. 트리거: **실제 온프레미스 추론 하드웨어 확보 또는 폐쇄망 배포 요구**. 단, P2의 `verified_tasks_per_hour` 지표는 현 DeepSeek 환경에서도 유용해 조기 추출 가능(별도 판단).

## Harness Adoption

- `deepseek-harness-adoption.md` — context/pruning/recovery/event logging 등 다수 반영. 당시 Planner 중심 내용은 현재 올인원 Developer 구조와 다를 수 있음.
- `claude-code-cleanroom-adoption.md` — permission/runtime steering/task lifecycle 아이디어 일부 반영. 별도 Reviewer/Debugger 기본 구조는 현재 제거됨.
- `hermes-agent-adoption.md` — Skills/selective retrieval/metrics 등 반영.

## Product / Capability

- `browser-computer-use.md` — **proposal**. Playwright 기반 Browser Use로 런타임·UI 검증 사각을
  메운다(build 통과를 '실제로 뜨고 동작함'으로 승격). 1단계는 verify에 런타임 스모크 추가(콘솔
  에러 0·셀렉터 렌더), 2단계 에이전트 도구화. Computer Use는 철학·안전 이유로 보류.
- `forge-runtime-hardening-roadmap.md` — **우선순위 로드맵 proposal**. Verification 3-state → ExecutionBackend → authoritative event/replay → benchmark-driven model routing → task worktree → RSI promotion → optional parallel Developer → visual loop 순으로 FORGE를 Verified Autonomous Software Execution Runtime으로 강화하는 제안.
- `global-workspace-skills.md` — **구현됨**. 실제는 Curated/Learned/Project 3-tier로 확장됨.
- `token-cost-reduction.md` — living research. 단, 비용 절감은 항상 success-rate gate 아래에 둔다.
- `low-cost-model-routing.md` — **proposal/experimental**. Ling 3.0 Flash·Qwen3.7 Flash 등 저가 모델을 동일 Developer Harness에서 CPS 기준으로 평가하고 privacy-aware fallback/routing을 도입하는 제안. (Ox Alpha는 2026-08-23 코드에서 제거 — 문서 내 상태 노트 참고.)
- `durable-worker-resume.md` — **핵심 Auto Resume 구현됨**. worker 완전 분리/권한 semantics는 추가 과제.
- `recursive-self-improvement.md` — **R0+R1 구현**. R0 deterministic benchmark + promotion gate + candidate worktree orchestration(`rsi_run.py`: worktree add→candidate-cmd→bench→gate→report, auto-merge 없음) 구현됨. R2(bottleneck→변경안 자동 제안)·R3(운영/감사 자동화) 미구현.
- `remote-terminal.md` — **v1 구현됨**. proposal의 Docker-only가 아니라 현재 Mac host PTY.
- `live-screen-preview.md` — **view-only 1차 구현**. WebRTC 고도화 미구현.
- `home-camera-monitor.md` — **JPEG polling PoC 구현**. WebRTC/Condition 연동 미구현.
- `scheduled-condition-jobs.md` — **Scheduled 기반 구현 중**. durable semantics/Condition/Deferred 고도화 필요.
- `forge-mcp-agent-runtime.md` — MCP server 관련 기반은 존재하지만 proposal 전체 autonomous runtime 계약은 별도 평가 필요.
- `prime-agent-adoption.md` — **A(Continual Harness Refinement) P0 커널 구현됨**(근거 수집·후보 생성·저장/rollback·승인 UX까지. 자동 적용 없음). B(Restricted Tool Script)는 벤치 결과 기각.
- `tauri-desktop-host.md` — proposal.
- `web-search-tools.md` — proposal/보류. 품질 개선 효과가 benchmark로 확인될 때 채택.
- `vision-agent.md` — Vision 기능 일부 구현.
- `gate-coverage-enforcement.md` — **proposal**. acceptance gate 생성이 모델 재량이라, gate 0개인 채로 `completed`가 나는 우회 경로가 있다(실측 프로브에서 재현). G1(정직 표기) 구현됨, G0(커버리지 계측)·G2(강제) 미착수 — G0 데이터를 보고 G2 방식을 정한다.

## 현재 구현과 과거 Proposal이 다른 대표 사례

- 기본 Agent 구조: 과거 Planner/Reviewer/Debugger 분리 → 현재 올인원 Developer + process verification.
- Durable Resume: 과거 미구현 → 현재 startup auto-resume 구현.
- Benchmark: 과거 계획 → 현재 21-task deterministic R0 harness 구현.
- RSI: 과거 설계 → 현재 promotion gate까지 구현.
- Skills: Global/Workspace 2-tier 제안 → Curated/Learned/Project 3-tier 구현.
- Terminal: Docker sandbox 제안 → host PTY v1.
- Camera: WebRTC 제안 → `imagesnap` polling PoC.

Proposal 본문은 역사적 설계 기록이므로 전부 현재형으로 덮어쓰지 않는다. 대신 이 인덱스에서 구현 상태와 divergence를 명시한다.

## 판단 원칙

```text
success_rate / correctness
→ verified completion
→ cost_per_success
→ elapsed
→ human intervention
```

저렴한 모델을 쓰는 것은 수단이다. **저렴한 모델로도 품질을 보장하게 만드는 Harness 프로세스가 제품의 핵심 기술**이다.
