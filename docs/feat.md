# FORGE — 기능 목록

## v1 포함 기능

| 기능 | 설명 | 상태 |
|---|---|---|
| Agent Loop | Planner → Tool Loop → Observation → Report | ✅ |
| DeepSeek V4 Pro 연동 | streaming + tool calling + thinking mode | ✅ |
| Tool Calling | function calling 기반 도구 호출 | ✅ |
| Docker Sandbox | 격리된 코드 실행 환경 | ✅ (bash 격리 실행) |
| 승인 게이트 | 위험 도구 실행 전 승인 | ✅ |
| SSE Streaming | 실시간 이벤트 스트리밍 | ✅ |
| Context Management | 토큰 사용량·버짓 관리 | ⬜ usage 전송 + 한도 중단만, compaction 예정 |
| Session 관리 | 대화 세션·히스토리 | ✅ (Postgres 영속화) |
| Checkpoint | 작업 단계별 git 스냅샷 | ⬜ git sha 기록만, 롤백 미구현 |
| HANDOFF 생성 | 컨텍스트 압축·인수인계 문서 | ⬜ Phase 3 |
| Mobile PWA 원격 제어 | 모바일에서 진행 확인·승인·중단 | ✅ (승인·질문·중단 UI) |

## v1 제외 (v2 이후)

- Multi-Agent
- MCP
- Repository AST Intelligence
- Vector Search
- Browser Agent
- Vision Agent
- 자체 모델 운영

## 도구 목록

| Tool | 설명 | 상태 |
|---|---|---|
| read_file | 파일 읽기 | ✅ |
| list_dir | 디렉터리 탐색 | ✅ |
| grep | 코드 검색 | ✅ |
| edit_file | 부분 수정 | ✅ |
| write_file | 파일 생성 | ✅ |
| bash | 명령 실행 (Sandbox) | ✅ |
| ask_user | 사용자에게 질문·확인 | ✅ |
| git | Git 관리 | ⬜ bash로 대체 가능, 전용 도구 미구현 |
| test | 테스트 실행 | ⬜ bash로 대체 가능 |

## 권한 정책

| 정책 | Tool |
|---|---|
| 자동 실행 | read_file, list_dir, grep, git status, git diff |
| 승인 필요 | edit_file, write_file, bash, git commit, dependency 변경 |
| 차단 | rm -rf, credential 접근, secret 출력, git push |

## PWA 기능

- 진행 상태 확인 ✅
- 추론(thinking) 표시 ✅
- 도구 호출·결과 표시 ✅
- 승인 ✅
- 중단 ✅
- 사용자 질문(시트) ✅
- Diff View ⬜
- SSE 재연결 ⬜ Phase 3
- Web Push ⬜ Phase 3
- Offline Shell ⬜ Phase 3
