# FORGE — 데이터베이스 스키마

> PostgreSQL 17 · 데이터베이스 `forge`

## 테이블 목록

| 테이블 | 용도 |
|---|---|
| `sessions` | 채팅방(워크스페이스) |
| `messages` | 대화 기록 |
| `tasks` | 칸반 태스크 |
| `checkpoints` | git 스냅샷 |

## sessions

채팅방. 각 방은 독립적인 워크스페이스 경로를 갖는다.

| 컬럼 | 타입 | 널 | 기본값 | 설명 |
|---|---|---|---|---|
| id | varchar | NOT NULL | - | 방 ID (PK, uuid) |
| title | varchar | NOT NULL | '' | 방 이름 |
| workspace_id | varchar | NOT NULL | '' | (레거시) 워크스페이스 식별자 |
| workspace_path | varchar | NULL | - | 실제 로컬 워크스페이스 경로 |
| status | varchar | NOT NULL | 'active' | 방 상태 |
| model | varchar | NOT NULL | '' | 사용 모델 |
| logical_budget | integer | NOT NULL | 262144 | 논리 컨텍스트 한도 (토큰) |
| used_tokens | integer | NULL | 0 | 현재 사용 토큰 수 |
| created_at | timestamp | NOT NULL | now() | 생성 시각 |
| archived_at | timestamp | NULL | - | 보관 시각 |

## messages

대화 메시지. content_json에 전체 메시지(role, content, tool_calls, reasoning_content)를 JSON으로 저장.

| 컬럼 | 타입 | 널 | 기본값 | 설명 |
|---|---|---|---|---|
| id | integer | NOT NULL | serial | 메시지 ID (PK) |
| session_id | varchar | NOT NULL | - | 방 ID (FK → sessions.id) |
| seq | integer | NOT NULL | - | 대화 내 순서 |
| role | varchar | NOT NULL | - | user / assistant / tool |
| content_json | text | NOT NULL | '{}' | 메시지 본문 (JSON) |
| prompt_tokens | integer | NOT NULL | - | 프롬프트 토큰 |
| completion_tokens | integer | NOT NULL | - | 응답 토큰 |
| cached_tokens | integer | NOT NULL | - | 캐시 토큰 |

## tasks

칸반 태스크. 상태는 `todo → planning → in_progress → review → debug ⇄ review → done`.

| 컬럼 | 타입 | 널 | 기본값 | 설명 |
|---|---|---|---|---|
| id | integer | NOT NULL | serial | 태스크 ID (PK) |
| session_id | varchar | NOT NULL | - | 방 ID |
| title | varchar | NULL | '' | 태스크 제목 |
| status | varchar | NULL | 'todo' | 상태 (todo/planning/in_progress/review/debug/done) |
| progress | integer | NULL | 0 | 진행률 (0~100) |
| created_at | timestamp | NULL | now() | 생성 시각 |
| updated_at | timestamp | NULL | now() | 갱신 시각 |

## checkpoints

변경 도구 실행 전 git 상태 스냅샷.

| 컬럼 | 타입 | 널 | 기본값 | 설명 |
|---|---|---|---|---|
| id | integer | NOT NULL | serial | 체크포인트 ID (PK) |
| session_id | varchar | NOT NULL | - | 방 ID (FK → sessions.id) |
| git_sha | varchar | NOT NULL | '' | git 커밋 SHA |
| step_no | integer | NOT NULL | - | 에이전트 스텝 번호 |
| created_at | timestamp | NOT NULL | now() | 생성 시각 |

## 관계

```
sessions 1 ── * messages    (session_id)
sessions 1 ── * tasks       (session_id)
sessions 1 ── * checkpoints (session_id)
```

`messages`·`checkpoints`는 `session_id`에 FK 제약이 걸려 있고, `tasks`는 아직 FK 없음.

## 확장 예정 (spec 18장)

요구사항서에 정의돼 있으나 미구현:

- `approvals` — 도구 승인 기록 (id, tool_call_id, decision, scope, requested_at, decided_at)
- `audit_logs` — 감사 로그 (id, actor, action, payload, created_at)
- `tool_calls` — 도구 호출 상세 (id, message_id, tool_name, args_json, result, status, risk_level, duration_ms)
