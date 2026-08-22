# FORGE Proposal Index / Adoption Status

> 기준: 2026-08-22 `main`

이 디렉터리의 문서는 작성 당시의 **설계 제안/참고 기록**이다. 현재 구현 상태의 authoritative 문서는 `../work_status.md`, `../architecture.md`, `../agent-loop.md`다.

Proposal 본문은 역사적 설계 의도를 보존하기 위해 완료된 항목을 일괄 삭제하거나 미래 시제로 다시 쓰지 않는다. 아래 표에서 현재 반영 상태를 확인한다.

## DeepSeek Harness Adoption

문서: [`deepseek-harness-adoption.md`](deepseek-harness-adoption.md)

| 제안 | 현재 상태 |
|---|---|
| Tool-result pruning | ✅ 구현 |
| Context compaction | ✅ 구현 |
| Model surface / stored history 분리 | ✅ 구현 |
| Provider retry/recovery | ✅ 구현 |
| read-only parallel tools | ✅ 1차 구현 |
| cancellation 개선 | ✅ pending wait 해제/timeout까지 구현 |
| durable event log | ✅ JSONL 추적 계층 구현 |
| authoritative replay stream | ⬜ 미구현 |
| 서버 재시작 후 true resume | ⬜ 미구현 |
| Tool Code/RPC mode | ⬜ 미구현 |

## Claude Code Clean-room Adoption

문서: [`claude-code-cleanroom-adoption.md`](claude-code-cleanroom-adoption.md)

| 제안 | 현재 상태 |
|---|---|
| Task lifecycle | ✅ 구현 |
| Reviewer/Debugger correction loop | ✅ 구현 |
| Permission/approval boundary | ✅ 구현 |
| Runtime steering | ✅ 구현 |
| Session live status | ✅ 구현 |
| Coordinator/isolated worker | ⬜ 미구현 |
| Background/durable worker | ⬜ 미구현 |

Claude 관련 proposal은 유출 코드를 복사하기 위한 문서가 아니라 공개적으로 확인 가능한 설계 아이디어를 독립적으로 재구현하는 clean-room 방향을 전제로 한다.

## Hermes Agent Adoption

문서: [`hermes-agent-adoption.md`](hermes-agent-adoption.md)

| 제안 | 현재 상태 |
|---|---|
| Self-Improving Skills 1차 | ✅ 구현 |
| Selective Skill Retrieval | ✅ 구현 |
| Prompt-cache-first stable prefix | ✅ 구현 |
| Session search | ✅ 구현 |
| Metrics / cost-first optimization | ✅ 구현 |
| Persistent reconnect | ✅ 구현 |
| 프로세스 재시작 후 execution resume | ⬜ 미구현 |
| Tool Script/RPC Mode | ⬜ 미구현 |
| Scheduled/Condition Jobs | ⬜ 미구현 |
| ExecutionBackend abstraction | ⬜ 미구현 |
| Isolated Subagents | ⬜ 미구현 |

## Vision Agent

문서: [`vision-agent.md`](vision-agent.md)

Vision request 사전 분석 및 `deepseek-v4-flash-vision-exp` 라우팅은 현재 구현되어 있다. 추가 Vision 고도화는 별도 과제다.

## FORGE의 현재 통합 방향

```text
DeepSeek Harness
  → compaction / recovery / durability 아이디어

Claude Code 분석
  → task lifecycle / permission / orchestration 아이디어

Hermes Agent
  → skills / prompt cache / persistent-agent 아이디어

FORGE
  → Flash-first DeepSeek + 작은 Python Runtime + 모바일 원격 제어
```

최상위 판단 기준은 기능 수가 아니라 **cost per successfully completed task**다.
