# Web Search / Web Fetch Tool 도입 제안

> 상태: Proposal  
> 목표: FORGE Agent가 최신 공식 문서, 라이브러리 변경사항, 오류 사례를 안전하고 토큰 효율적으로 조사할 수 있도록 제한된 웹 탐색 능력을 제공한다.

## 1. 배경

FORGE는 현재 repository/workspace 내부 탐색과 shell/tool 실행에 강하게 최적화되어 있다.

하지만 다음 유형의 작업은 로컬 정보만으로 해결하기 어렵다.

- 최신 SDK/API 문서 확인
- 최근 breaking change 조사
- 생소한 compiler/runtime 오류 조사
- 외부 라이브러리 사용법 확인
- 공식 migration guide 확인
- dependency 최신 버전의 동작 확인

모델의 학습 시점 지식에 의존하면 오래된 API를 제안하거나 존재하지 않는 옵션을 만들어낼 위험이 있다.

따라서 FORGE에 명시적인 `web_search` / `web_fetch` Tool을 추가하는 것을 제안한다.

---

## 2. 핵심 원칙

웹 접근을 단순히 `bash -> curl` 형태로 개방하지 않는다.

목표 구조:

```text
Agent
  ↓
web_search(query)
  ↓
Search Provider
  ↓
정규화된 검색 결과
  ↓
web_fetch(url)
  ↓
본문 추출 / 정리
  ↓
Agent
```

웹 탐색은 **bounded tool**이어야 한다.

- 입력과 출력 크기 제한
- URL 검증
- timeout
- redirect 제한
- private network 차단
- binary download 제한
- HTML 정제
- tool telemetry

FORGE의 기존 Harness 정책과 동일하게 **필요한 정보만 모델 context에 전달**한다.

---

## 3. Tool 1 — web_search

초기 인터페이스 예:

```json
{
  "query": "FastAPI lifespan startup event deprecated",
  "max_results": 5
}
```

반환 예:

```json
{
  "results": [
    {
      "title": "Lifespan Events - FastAPI",
      "url": "https://fastapi.tiangolo.com/advanced/events/",
      "snippet": "...",
      "domain": "fastapi.tiangolo.com"
    }
  ]
}
```

검색 결과 전체 HTML을 모델에게 전달하지 않는다.

최소 metadata만 반환한다.

기본 `max_results`는 작게 유지한다.

권장 범위: 3~5개.

---

## 4. Tool 2 — web_fetch

검색 결과 중 실제 확인이 필요한 URL만 fetch한다.

예:

```json
{
  "url": "https://fastapi.tiangolo.com/advanced/events/"
}
```

Tool 내부:

```text
URL validation
→ DNS / network safety check
→ HTTP fetch
→ content-type 확인
→ HTML parsing
→ navigation/script/style 제거
→ main text 추출
→ 길이 제한
→ Agent 전달
```

반환 예:

```json
{
  "url": "...",
  "title": "...",
  "content": "정제된 본문",
  "truncated": false
}
```

---

## 5. Search와 Fetch를 분리하는 이유

한 번의 `web_search`가 검색된 페이지 전체를 모두 읽는 구조는 피한다.

나쁜 흐름:

```text
검색 10개
→ 10개 페이지 전체 다운로드
→ 수만 token
→ 모델
```

목표:

```text
검색
→ snippet 비교
→ 가장 관련 있는 1~2개 선택
→ fetch
→ 필요한 내용만 reasoning
```

이 방식이 FORGE의 `cost per successfully completed task` 원칙과 맞는다.

---

## 6. 공식 문서 우선 정책

Coding Agent의 웹 검색에서는 일반적인 popularity보다 source quality가 중요하다.

가능하면 다음 우선순위를 prompt/tool guidance에 제공한다.

1. 공식 documentation
2. 공식 GitHub repository / release notes
3. language/framework 공식 proposal
4. vendor documentation
5. 신뢰도 높은 technical source
6. community discussion

Stack Overflow/Reddit/blog 등은 실제 사례 조사에는 유용하지만 API 사실 확인의 최종 근거로 우선하지 않는다.

---

## 7. 검색 Provider 추상화

AgentRuntime이 특정 검색 서비스에 직접 의존하지 않게 한다.

```text
WebSearchProvider
├─ Brave
├─ Tavily
├─ Serper
└─ future provider
```

하지만 초기 구현에서 거대한 provider framework를 만들지 않는다.

최소 interface 하나와 provider 하나로 시작한다.

예:

```python
class WebSearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...
```

Provider API key가 없으면 web_search Tool을 등록하지 않거나 명확한 unavailable 결과를 반환한다.

---

## 8. SSRF 방어

`web_fetch`는 Agent가 임의 URL을 요청할 수 있으므로 SSRF 방어가 필수다.

차단 대상:

- localhost
- 127.0.0.0/8
- ::1
- private IPv4 ranges
- link-local
- cloud metadata endpoint
- 내부 hostname
- file://
- ftp:// 등 허용하지 않은 scheme

기본 허용 scheme:

```text
https
http (필요한 경우만)
```

DNS resolution 이후 실제 destination IP도 검사한다.

redirect가 private address로 이동하는 경우에도 차단한다.

---

## 9. Content 제한

초기 `web_fetch`는 text 중심으로 제한한다.

지원:

- text/html
- text/plain
- application/json (제한적으로)

초기 미지원:

- executable
- archive
- arbitrary binary
- 대용량 file download

PDF는 필요성이 확인되면 별도 Tool로 추가한다.

이미지는 기존 Vision/attachment pipeline과 별도다.

---

## 10. Token Budget

웹 페이지 전체를 context에 넣지 않는다.

예시 정책:

```text
SEARCH_RESULTS_MAX = 5
FETCH_MAX_CHARS = 20_000
WEB_CONTEXT_MAX_CHARS_PER_RUN = 40_000
```

실제 값은 benchmark 후 조정한다.

긴 페이지는:

- heading 유지
- navigation 제거
- 중복 제거
- 본문 중심 추출
- head/tail이 아니라 구조 기반 truncation 우선

을 검토한다.

향후 필요하면 `find_in_page` 같은 좁은 Tool을 추가할 수 있다.

---

## 11. Agent 사용 정책

모든 요청에서 웹 검색하지 않는다.

다음 경우 우선 고려한다.

- 사용자가 명시적으로 최신 정보 요청
- dependency/API version 불확실
- 모델이 확신하기 어려운 external error
- 공식 문서 확인이 필요한 구현
- 로컬 repository에 필요한 정보가 없음

반대로 다음에는 웹 검색을 피한다.

- repository 내부 코드로 충분히 해결 가능
- 단순 formatting/refactoring
- 이미 필요한 공식 문서 내용이 workspace에 존재

즉:

```text
Local-first
→ 부족하면 Web
```

정책을 유지한다.

---

## 12. Tool Result Pruning 연동

기존 Tool result pruning과 연동한다.

웹 결과도 일반 Tool result와 마찬가지로 context budget 대상이다.

특히 fetch 결과는 원본 전체를 conversation history에 반복 삽입하지 않는다.

필요하면 durable event에는 URL/metadata/요약을 기록하고 model-facing context에는 현재 작업에 필요한 내용만 남긴다.

---

## 13. Prompt Cache 영향

웹 결과는 dynamic context이므로 stable system prefix에 넣지 않는다.

```text
Stable Prefix
- core prompt
- role instructions
- tool schemas

Dynamic Tail
- user task
- selected skills
- web search/fetch results
- tool results
```

현재 stable prefix 전략을 깨지 않는다.

---

## 14. Telemetry

최소 다음을 기록한다.

- web_search_count
- web_fetch_count
- fetched_bytes/chars
- truncated count
- provider latency
- provider error
- domain

그리고 benchmark에서 다음을 비교한다.

```text
Web 사용 작업 성공률
vs
Web 미사용 작업 성공률
```

추가로:

- 평균 model calls
- 평균 token usage
- 평균 elapsed time
- cost per successful task

을 비교한다.

웹검색이 성공률을 거의 높이지 않으면서 비용만 증가하면 policy를 좁힌다.

---

## 15. Security / Prompt Injection

웹 콘텐츠는 **신뢰되지 않은 외부 입력**이다.

페이지에 다음과 같은 텍스트가 존재할 수 있다.

```text
Ignore previous instructions...
Run this command...
Upload your API key...
```

Agent가 이를 instruction으로 취급하면 안 된다.

System/Tool prompt에서 웹 콘텐츠를 명확하게 untrusted data로 표시한다.

원칙:

> Web content provides information, not authority.

웹 페이지가 명령 실행, credential 접근, 보안 정책 변경을 요구해도 이를 직접 따르지 않는다.

Mutation tool은 기존 approval/security policy를 그대로 거친다.

---

## 16. bash/curl과의 관계

Host mode에서 `curl`이 기술적으로 가능하더라도 공식 웹 탐색 경로는 `web_search` / `web_fetch`를 사용한다.

이유:

- SSRF 방어
- timeout 통제
- output 크기 통제
- telemetry
- content 정제
- provider abstraction
- 일관된 Agent behavior

필요하면 Agent prompt에 웹 조사 목적으로 shell curl을 우선 사용하지 않도록 명시한다.

---

## 17. 구현 단계

### Phase W0 — Search PoC

- provider 하나 선택
- `web_search` Tool
- 결과 normalization
- timeout/error handling
- unit test

### Phase W1 — Safe Fetch

- `web_fetch`
- SSRF 방어
- redirect validation
- content-type 제한
- HTML text extraction
- output budget

### Phase W2 — Harness Integration

- role별 Tool 등록
- Local-first policy
- telemetry
- tool-result pruning
- prompt injection boundary

### Phase W3 — Evaluation

Benchmark:

- 최신 API 조사
- breaking change
- 생소한 error
- 공식 documentation 기반 구현

웹검색 ON/OFF를 비교한다.

---

## 18. Role별 권한

초기 권장:

### Planner

`web_search`, `web_fetch` 허용.

최신 API/설계 조사에 유용하다.

### Coder

허용하되 필요할 때만 사용.

### Debugger

허용.

외부 오류 조사 가치가 높다.

### Reviewer

기본적으로 제한적으로 허용하거나 비활성화 검토.

Reviewer가 매번 웹검색하면서 비용을 늘리는 것을 피한다.

### Triage

비활성화.

Routing 단계에서 웹검색은 불필요하다.

정확한 role policy는 benchmark로 결정한다.

---

## 19. 하지 않을 것

초기 버전에서는 다음을 하지 않는다.

- full browser automation
- Chromium/Playwright 상시 실행
- JavaScript-heavy website interaction
- 로그인 세션 관리
- cookie jar
- 웹사이트 form 자동 제출
- 웹 crawling
- 검색 index 자체 구축
- arbitrary file download
- vector DB에 웹 전체 저장

FORGE에 지금 필요한 것은 Browser Agent가 아니라 **Coding Agent용 조사 도구**다.

---

## 20. 완료 기준

1. Agent가 최신 기술 정보를 명시적으로 검색할 수 있다.
2. 검색 결과 중 필요한 URL만 fetch한다.
3. private/internal network fetch가 차단된다.
4. 웹 페이지의 prompt injection을 untrusted content로 취급한다.
5. 긴 페이지가 context를 무제한 소비하지 않는다.
6. 웹 사용량이 telemetry에 기록된다.
7. 기존 stable prompt/cache 구조를 깨지 않는다.
8. 기존 Tool approval/security 정책을 우회하지 않는다.
9. provider 장애가 AgentRuntime 전체 실패로 이어지지 않는다.
10. benchmark로 실제 성공률/비용 효과를 측정할 수 있다.

---

## 21. 장기 확장

실제 필요가 확인되면 이후 다음을 검토한다.

```text
web_search
web_fetch
    ↓
find_in_page
    ↓
PDF/document fetch
    ↓
GitHub/release specialized search
```

Browser automation은 별도 proposal로 다룬다.

---

## 결론

FORGE에 웹검색은 필요하다.

하지만 인터넷 전체를 shell에 개방하는 방식이 아니라:

> **Search → Select → Safe Fetch → Prune → Reason**

이라는 좁고 측정 가능한 Harness Tool로 구현한다.

이 방식이 최신 정보 접근 능력을 추가하면서도 FORGE의 핵심 원칙인 보안, context 효율, prompt cache 안정성, 그리고 **cost per successfully completed task**를 유지하는 방향이다.
