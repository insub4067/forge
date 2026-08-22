# FORGE Agent Runtime 구조

`backend/app/runtime/agent.py`의 `AgentRuntime.run()`이 오케스트레이션한다.

## 흐름
```
Triage ─(chat)→ 단일 Chat 패스(읽기전용 도구)
   │(agent)
Planner → Coder → [ Reviewer ↔ Debugger 자기수정 루프 ]
```
- **task 상태가 authority**: Reviewer가 done/debug, Debugger가 review로 되돌림. 모든 task done이어야 성공.
- 자기수정 루프 최대 `MAX_REVIEW_CYCLES`(3)회, 초과 시 남은 문제 보고(`review_limit`).

## 생존 계층 (건드릴 때 주의)
- **컨텍스트 압축**: 75% 넘으면 오래된 대화를 flash로 요약해 모델 컨텍스트만 축소(비파괴). `_safe_split`로 tool_call/result pair 경계 보존 — orphan tool 만들지 말 것.
- **도구 결과 pruning**: 긴 결과는 앞뒤+오류만 남겨 모델에 전달(`_prune_tool_result`). UI는 원본.
- **오류 회복**: `_stream_with_recovery` — reasoning_content 400은 벗겨 재시도, 429/5xx/timeout은 백오프 재시도, terminal은 전파.
- **읽기 도구 병렬**: 한 응답의 read_file/list_dir/grep가 여러 개면 prefetch로 병렬.

## 종료 상태
done 이벤트 `data.status`: completed / review_limit / cancelled / context_blocked / max_steps / repeated_tool_call / failed.

## 안전
- SSE 이벤트 프로토콜을 대규모로 깨지 말 것(모바일이 계속 처리해야 함).
- 도구 스키마 순서·system prompt를 세션 중 불필요하게 바꾸지 말 것(prompt cache).
