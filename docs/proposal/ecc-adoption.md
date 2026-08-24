# ECC(Everything Claude Code) 선별 도입 검토

> 2026-08-25. FORGE `main` 실제 source와 ECC(`github.com/affaan-m/ECC`, npm `ecc-universal` v2.2.0, MIT) 실제 구조를 대조한 결과다.
> 최종 판정: **SELECTIVE_ADOPTION** — 단, 실질 net-new는 사실상 Security Preflight 하나다.

## 1. ECC 개요

ECC는 여러 harness(Claude Code 중심, Codex/Cursor/OpenCode 등)를 겨냥한 "agent harness OS"다. 루프는 `plan → test → implement → review → verify → remember → improve`. 구성은 크게 다섯이다.

- **Agents**: `agents/*.md`, YAML frontmatter(`name/description/tools/model`). 유지자 주장 68개. planner/coder/reviewer/debugger/builder + 언어별 reviewer·build-resolver 20여 종. 선택은 frontmatter `description` 기반 host 모델 auto-delegation(비결정적). tool 제한만 결정적.
- **Skills**: `skills/*/SKILL.md`, 주장 286개. on-demand progressive disclosure(전량 주입 아님). 별도로 `rules/`는 항상 로드되는 컨텍스트.
- **Hooks**: `hooks/hooks.json` + `scripts/hooks/*.js`. **실제 Node 스크립트**, 모델 컨텍스트 밖에서 실행(토큰 0). 7개 이벤트·약 23개 훅. 프로파일 env(`ECC_HOOK_PROFILE=minimal|standard|strict`)로 on/off.
- **Continuous Learning v2("instincts")**: 관찰 캡처(훅) → 패턴 탐지(백그라운드 Haiku) → confidence(0.3~0.9) 부여 → `/evolve`로 skill 승격 → project→global 승격(같은 instinct가 2개 이상 프로젝트 + 평균 confidence ≥0.8). 저장·threshold·승격은 결정적 스크립트, 패턴 판단만 LLM.
- **AgentShield**: `.claude/` 설정 표면(CLAUDE.md/settings.json/mcp.json/hooks/agents) + 시크릿 패턴 스캔, A~F 등급, critical에서 exit 2. **주의**: 결정적 룰 엔진(102 rule 주장)은 별도 npm 패키지 `ecc-agentshield`에 있고 이 repo에는 미배선. repo 안에 있는 건 `skills/security-scan/SKILL.md`(프롬프트/문서)뿐이라 결정성은 repo 기준 검증 불가.

숫자(68/286/102/14)는 전부 유지자 주장이며 트리에서 정확히 세지 못했다.

## 2. ECC vs FORGE 구조 비교

| 축 | ECC | FORGE 현재(실코드) | 격차 | 조치 |
|---|---|---|---|---|
| Agent topology | planner/coder/reviewer/debugger + 언어별 68 subagent, 비결정적 auto-delegation | 올인원 Developer 기본, 복잡 작업만 경량 Planner→Developer→Reviewer 1방향. `_estimate_complexity()` agent.py:514 | FORGE가 더 적고 더 통제됨 | **KEEP FORGE** |
| Skills | 286 SKILL.md, on-demand 로드, 별도 always-on `rules/` | Curated/Learned/Project 3-tier + 키워드 selective retrieval(top3, 6000자, prompt-cache 안전 tail) skills.py, agent.py:212 | lifecycle(자동 승격)·A/B만 부재 | improve(experiment) |
| Hooks | hooks.json + Node 스크립트, 7 이벤트, 컨텍스트 밖, 프로파일 | **범용 seam 없음**. 정책이 `_run_role` if-브랜치(agent.py:1287-1414)·`execute_tool`(registry.py:531)에 인라인 | 범용 registry 없음(단, enforcement는 이미 존재) | **REFERENCE_ONLY** |
| Memory / 학습 | Memory Vault(평문) + instinct(evidence→confidence→승격) | `memory_guard.validate_candidate()`로 claim 토큰이 인용 source에 실존하는지 결정적 검증 + evidence를 이번 run gate에 결박. `refine.py`는 2회+ 재현된 failure signature만 후보화 | positive-behavior confidence 강화 축만 얇음 | 대체로 있음 / 소폭 experiment |
| Security scan | AgentShield(단, 딥 엔진은 외부 패키지) | **workspace secret/injection 스캔 없음** | **진짜 gap** | **ADOPT(소규모)** |
| Benchmark/RSI | 없음(instinct 승격 규칙만) | R0 25 fixture + `promotion_gate()` lexicographic(success→CPS→elapsed), worktree 격리, 자동 merge 금지 | FORGE가 우위 | **KEEP FORGE** |

핵심: ECC 4대 관심축(Hook / Evidence-backed Memory / Security Preflight / 검증된 소수 Skill) 중 **3개는 FORGE에 이미, 종종 더 엄격하게 구현돼 있다.**

## 3. 가져올 기능

**Security Workspace Preflight(결정적 스캐너) 하나만 실제 도입한다.** 이유는 8절.

## 4. 가져오지 않을 기능

- 68 Agent / 286 Skill 일괄 이식 — 프롬프트 명시 금지, FORGE 정체성 훼손.
- planner/reviewer/debugger role 부활 — FORGE는 이미 복잡 작업만 경량 멀티로 축소했고 과거 planner 73% 비용 문제를 구조적으로 제거했다(agent-mode-decision-2026-08-24).
- ECC식 Node 훅 프레임워크(7 이벤트 registry) — FORGE 런타임은 in-process Python 단일 루프라 out-of-context Node 훅 모델이 맞지 않고, enforcement 지점은 이미 fail-closed로 존재한다. 범용 registry는 프롬프트가 경고한 plugin framework 과설계다.
- LangGraph/CrewAI/새 agent framework, 런타임 전면 재작성 — 전부 비대상.

## 5. Skills 분석

FORGE 3-tier(skills.md)는 ECC의 flat 286과 목적이 다르다. FORGE는 "모델이 자주 실수하는 절차 + 프로젝트 특화 workflow"만 소수 유지하고 키워드로 top3만 주입한다. ECC가 나은 단 하나는 **결정적 승격 규칙**이다: 같은 instinct가 2+ 프로젝트에서 avg confidence ≥0.8이면 project→global. FORGE는 `save_skill` project→learned 자동 승격을 의도적으로 미구현으로 뒀다(skills.md). 이 규칙은 나중에 skill 승격에 참고할 값이다. 지금 도입하지는 않는다(측정된 병목 없음, YAGNI).

## 6. Hooks 분석

ECC 훅의 진짜 가치는 "정책을 모델 프롬프트가 아니라 결정적 코드로, 컨텍스트 밖에서 강제"다. 이 원칙 자체는 FORGE가 이미 지키고 있다.

- commit gate: `finish()`가 `verification_failed`를 아예 `_autocommit`에 넘기지 않는다(agent.py:2163, 2440-2464). push는 fully-verified `completed`만(agent.py:2178). ECC의 before_commit보다 강한 런타임 invariant다.
- 위험명령: `BLOCKED_COMMANDS`(registry.py:290) + `_is_dangerous` 정규식(executor.py:9).
- gate 검증: 모델이 `passed`를 못 쓰게 clamp(agent.py:509), 실제 재실행으로만 부여(agent.py:1743).

없는 건 이 정책들을 한 곳에 모으는 **범용 seam**뿐이다. 지금 필요가 하나(Preflight)뿐이라 프레임워크를 만들 이유가 없다. Preflight는 `run()` 시작점에서 직접 호출하면 된다. 정책이 3개 이상으로 늘면 그때 `execute_tool`(registry.py:531)과 `run()` 시작 두 지점에 얇은 seam을 넣는다(YAGNI, 지금은 아님).

## 7. Memory 분석

FORGE의 evidence-bound 승격은 ECC instinct보다 오염에 강하다. `memory_guard`는 fact의 claim 토큰(백틱 코드, `/api/...`, 알려진 기술명)이 인용 source에 문자열로 실존하는지 결정적으로 확인하고, evidence는 이번 run의 실제 gate여야 한다. 실제 오염 사례(허위 WebSocket/WebRTC fact) 이후 하드닝됐다(memory_guard.py 헤더). ECC가 가진 얇은 추가 축은 "교정 없이 반복 관찰되면 confidence 상승"이라는 positive 강화다. FORGE의 `refine.py`는 failure 축만 본다. 이 positive 축은 소규모 실험 후보로만 남기고 지금은 손대지 않는다(P2는 사실상 완료 상태).

## 8. Security 분석

이게 유일한 실질 도입이다. 근거는 FORGE가 ECC보다 위험 권한이 크다는 점이다.

FORGE는 host mode 실행 + git push + Terminal PTY + MCP를 쓴다. 동시에 `GLOBAL_MEMORY.md`·`ROOM_MEMORY.md`·`.forge/skills/*.md`·MCP config를 **system prompt에 주입**한다(agent.py:194,200,272). 이 파일들은 에이전트 자신이나 외부 repo가 쓸 수 있어 prompt-injection 벡터다. 또 workspace에 커밋된 `.env`·개인키가 auto-push로 유출될 수 있다.

ECC AgentShield의 좋은 통찰은 "일반 workspace가 아니라 **에이전트가 실제 삼키는 설정 표면**을 스캔"이다. FORGE판 Preflight는 두 표면을 결정적 정규식으로 본다.

1. **Secret 유출**: git이 추적 중인 `.env`, `-----BEGIN … PRIVATE KEY-----`, `AKIA[0-9A-Z]{16}`, `sk-…`, `ghp_…` 등.
2. **Injection 표면**: FORGE가 주입하는 `ROOM_MEMORY.md`/`GLOBAL_MEMORY.md`/`.forge/skills/*.md` 안의 "ignore previous instructions / disregard the above / new system prompt" 류 패턴.

등급은 LOW/MEDIUM/HIGH 3단계(A~F는 과함). **DX 보호를 위해 기본 fail-open** — 결과를 이벤트/경고로 표면화하되 정상 실행을 막지 않는다. HIGH만 사용자 확인을 권고한다. `--opus` 같은 LLM 적대 파이프라인은 도입하지 않는다(비용·비결정성).

## 9. Context 전략

"컨텍스트엔 지금 task에 필요한 것만, 나머지는 영속" 원칙은 FORGE가 이미 실행 중이다: compaction(0.75) + tool-result pruning + tool_store + 3-tier selective skills + evidence-bound memory + JSONL event log + DB 영속. 추가 작업 없음. Preflight 결과도 컨텍스트를 늘리지 않게 HIGH 요약 한 줄만 표면화하고 상세는 event log에 둔다.

## 10. Benchmark 계획

Preflight는 관찰 전용(fail-open)이라 R0 success_rate를 구조적으로 낮출 수 없다. 그래도 회귀 확인은 한다.

- 스캐너 자체: `test_preflight.py` 결정적 유닛(양성/음성/경로탈출/등급).
- 런타임 배선(관찰 전용) 후: 기존 `test_developer_loop.py`·`test_agent_mode_loop.py` 통과 확인.
- (선택) HIGH→approval 게이팅을 나중에 배선하면 그때만 R0 재측정. success 하락 시 되돌린다.

## 11. 구현 우선순위

프롬프트 예상(P0 분석 → P1 Hook → P2 Memory → P3 Security → P4 Skills)을 실측 후 수정한다.

- P0: 이 문서(gap matrix) — **완료**.
- P1: **Security Preflight 스캐너 + 테스트** — 유일한 실질 net-new, 작고 결정적. 최우선.
- P2(REFERENCE): Hook seam — 정책이 3개 이상 될 때만. 지금 미실행.
- P3(REFERENCE): instinct식 skill 자동 승격(2+ project, conf≥0.8) — 측정된 병목 생기면.
- P2(ECC 예상)·Memory: 이미 구현 — 재작업 금지.

## 12. 위험 요소

- Preflight false positive가 DX를 해치는 것 → fail-open 기본 + HIGH만 확인으로 완화.
- 런타임 배선이 R0에 영향 → 관찰 전용으로 시작, 게이팅은 분리·후속.
- ECC 코드 복사 위험 → 아이디어만 흡수, 코드 미복사. MIT라 참고는 자유이나 attribution 필요 코드 재사용은 안 한다.

## 13. 예상 효과

성공률·CPS는 Preflight로 오르지 않는다(보안 기능이다). 효과는 "host mode + auto-push 환경에서 시크릿 유출/주입 사고를 작업 전에 결정적으로 표면화"라는 안전 이득이다. 토큰 영향은 HIGH 요약 한 줄로 무시 가능.

## 14. 최종 추천

**SELECTIVE_ADOPTION.** 단, 흡수 대상은 4개 축 중 사실상 1개(Security Preflight)다. 나머지 3축(Hook enforcement / Evidence-backed Memory / 검증된 소수 Skill)은 FORGE가 이미, 여러 지점에서 더 엄격하게 구현했으므로 재구현하지 않는다. ECC의 진짜 기여는 "에이전트가 삼키는 설정 표면을 결정적으로 스캔한다"는 보안 관점 하나다.
