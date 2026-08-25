# 세션 인수인계 — planner 비용 재실측 + reasoning_content 재전송 절감 (2026-08-25)

> 사용자가 FORGE 진화 작업을 이어받게 했다. "측정된 가치 순으로 골라라 — Phase 번호 소진이
> 목표가 아니다"가 전제. 이 세션은 **planner 비용 병목을 실측으로 재확인**하고, 그 결과 병목이
> planner가 아니라 developer였음을 밝힌 뒤 입력 토큰 재전송을 줄였다.

> ⚠️ 후속 정정(이 문서 작성 이후, 같은 세션): 아래 §1의 **reasoning_content 상시제거는
> 되돌려졌다.** DeepSeek V4 thinking mode 계약이 정반대(thinking+tools면 이전 assistant
> reasoning_content를 후속 요청에 **반드시 되돌려줘야** 하고 누락 시 400)임이 실서버·공식
> 문서로 확인됐다. 상시제거는 모든 thinking tool-loop를 400→thinking off로 전락시키는 P0
> 회귀였다. capability 기반(`requires_reasoning_replay`)으로 수정 완료. **§1의 −19.7% 절감은
> 무효**이며, 유효하게 남은 절감은 write_file fold(−13%)뿐이다. 최신 상태는
> `handoff-2026-08-26-reliability-hardening.md` 참조.

## 0. TL;DR — 다음에 할 일

**"토큰 절감"이 목표가 아니다.** 판단 기준은 *측정된 가치*. 이 세션은 비용 병목을 재실측해
잘못 알던 것을 바로잡았다(옛 메모리의 planner 73%는 stale). 남은 후보는 §6.

## 1. 이번 세션에 한 것

### planner 비용 병목 재실측 — 병목은 planner가 아니었다
telemetry(agent_runs) 712 run 실측(2026-08-22~25, 총 $16.00):

| role | $ | 비중 | run당 콜 | 콜당 입력 |
|---|---|---|---|---|
| **developer** | 11.26 | **70.4%** | 9.0 | 46,325 |
| planner | 2.44 | 15.2% | — | 32,675 |
| chat / reviewer / coder | 2.30 | 14.4% | — | — |

- **옛 메모리의 "planner 73%"는 stale이었다.** planner는 이미 `_planner_context`(최근 8메시지,
  tool 이력 제외)로 축소 컨텍스트만 받도록 고쳐져 있었다. 그 stale 값이 초기 우선순위를 잘못
  이끌었다.
- developer 비용의 **90%가 입력 토큰**(cache_hit $7.68 + miss $2.45), 출력 $1.13뿐. cache hit
  91.7%라 캐시 튜닝 여지 없음.
- 콜당 46K 중 **고정 오버헤드는 4K뿐**(system 1.8K + tool schema 2.2K) → 나머지 42K가 히스토리
  재전송.
- 실제 히스토리(세션 5c34d84f, 289메시지 110.8K tok) 구성: tool 결과 35.3% /
  **assistant.reasoning_content 30.3%** / tool_call args 28.7%(write_file 최대) / user 4.4% /
  content 1.3%.

### reasoning_content 재전송 제거 (⚠️ 이후 되돌려짐 — 문서 상단 정정 참조)
- reasoning_content가 히스토리의 30.3%인데, (당시 근거로는) "DeepSeek 계약상 되돌려주면 안
  된다"고 보고 전송본에서 상시 제거. 400을 겪은 세션만 반응적으로 벗기던 것을 전 세션 상시로.
- **`agent.py:725`** — `_stream_with_recovery`가 전송본에서 항상 reasoning을 벗김. 원본
  히스토리·Debug view는 보존.
- **`agent.py:749`** — 죽은 `stripped` 상태변수 제거, recovery는 `no_think`만으로 판정(동작 동일).
- 실측 시뮬레이션(세션 5c34d84f, 140콜): 누적 입력 8,556,521 → 6,867,668 tok(**−19.7%**).
  developer 입력이 비용의 90%이므로 총지출 기준 대략 −12%.
  → **후속 정정: 이 절감은 계약 위반 위에 세운 것이라 무효. reasoning은 유지가 정답.**

## 2. 검증 상태
- **pytest 206 passed / 회귀 0** (세션 시작 205 + reasoning 회귀 테스트 1).
- 신규 테스트: `test_reasoning_content_not_resent`(strict fake adapter로 전송본 제거·원본 보존
  검증). → 후속: 잘못된 계약을 정답으로 고정한 이 테스트는 이후 올바른 계약(round-trip 유지)
  테스트로 교체됨.
- 검증 원칙 준수: 테스트 삭제·완화·skip 없음.

## 3. 커밋 여부 (중요)
- **이 세션 시점에는 아직 커밋 안 됨.** 다음 세션에서 검토 후 커밋 여부 결정 필요 — 로 남겼었다.
- → 후속: `b01da1c`로 커밋·push됐으나, 이후 reasoning 계약 위반이 밝혀져 `0c59b11`로
  정정(capability 기반 round-trip 유지)됐다. write_file fold는 `f6341c3`로 유효하게 남음.

## 4. MEMORY.md — cost-bottleneck-planner 갱신
- 메모리 description을 `"planner가 73%"` → `"현재 developer 70%(히스토리 재전송)가 병목,
  planner 73%는 옛 수치"`로 교체.
- 본문에 "재실측(2026-08-25)" 섹션 추가: developer 70.4% 분해, planner 73% 해소 근거,
  reasoning 30% / tool_call args 29% / tool결과 35% 구성.
- → 후속: reasoning 제거 −19.7% 주장이 무효화됐으므로 "정정(GPT 리뷰)" 섹션을 추가해
  reasoning은 계약상 유지 필요, 유효 절감은 write_file fold −13%뿐임을 기록.

## 5. 재작성 금지 근거 (다시 조사할 필요 없는 것)
- **planner는 이미 최적화됨**: `_planner_context`가 최근 8메시지·tool 이력 제외로 축소
  컨텍스트만 준다. planner 알고리즘 손대지 말 것 — 73%는 옛 regime 수치다.
- **tool 결과(35%)는 이미 트리밍됨**: `_prune_tool_result`(head 1400 + tail 900자), 원본은
  `tool_store`에 저장(read_tool_result로 복구). 더 줄이면 성공률 트레이드오프.
- **비용 병목 분해(developer 70%, 입력 90%, 히스토리 재전송)** 는 유효 — 재실측 불필요.

## 6. 다음 할 일 후보 (우선순위 순)
1. **tool_call args 압축** (우선순위 1) — 히스토리의 28.7%, write_file 인자가 파일 전문을
   담은 채 영구 잔류(한 세션 13.5K tok). 파일은 디스크에 있고 read_file로 재조회 가능하므로
   전송본에서만 오래된 write_file 인자를 스텁으로 접으면 **~10% 추가 절감**. 단 이건 관찰
   전용이 아니라 모델이 보는 컨텍스트를 바꾸는 **핵심 런타임 변경**이라 최소 침습안 확인이
   필요했다 — **이 세션에선 미결정으로 남김.**
   → 후속: `f6341c3`으로 구현됨(성공한 과거 write만·최근 밖만·원본 보존·전송 projection만).
2. **Task IR 실세션 관측** — `TASK_IR_ENABLED=1`로 켜서 traceability 이벤트·false_completion
   후보가 유의미한지 A/B 관측 후 라우팅 채택 결정. 서버 구동 + 실세션 필요(사용자 운전 영역,
   self-repo 자기편집 위험). DB에 세션 원문·gate 데이터가 있어야 관측 가능.
3. **write-only checkpoint 결정** — `save_checkpoint`가 승인형 도구 전 (git_sha, step) 기록하나
   `select(Checkpoint)` 소비자 부재. rollback 배선 or dead capability 제거. 요청 없이 짓지 않음.
   → 후속: `6d00eb4`로 dead writer 제거 결정(git_sha가 step마다 안 변해 rollback 지점 부재 +
   기존 검증 게이트가 나쁜 상태 영속화를 이미 차단 + git reset은 비가역). 테이블·모델·FK
   정리 경로는 유지.

## 7. 핵심 파일
- 비용 재실측 스크립트: scratchpad(cost.py·dev.py — 일회성). 실 데이터는 `agent_runs`(telemetry).
- reasoning 처리: `backend/app/runtime/agent.py`(`_stream_with_recovery`) · deepseek 어댑터
  `app/llm/deepseek.py`
- 메모리: `~/.claude/projects/.../memory/cost-bottleneck-planner.md`
