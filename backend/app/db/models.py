from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, default="")
    workspace_id: Mapped[str] = mapped_column(String, default="")
    workspace_path: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # 방 모드 — "" (auto: triage로 chat/code 자동 분류, 하위호환) | "chat" (읽기전용 대화만)
    # | "work" (항상 작업 경로 + 검증·커밋, 워크스페이스 필수). triage 비용·오분류를 없앤다.
    mode: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active")
    model: Mapped[str] = mapped_column(String, default="")
    logical_budget: Mapped[int] = mapped_column(Integer, default=131072)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # run이 실행 중인지 영속화한다 — 서버 재시작으로 중단된 run을 시작 시 감지하기 위함.
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    # 마지막 run의 종료 상태 — 성공 정의(completed)와 세션 집계의 기준.
    final_status: Mapped[str] = mapped_column(String, default="")
    # 이 세션의 승인 정책(사용자가 정한 것). durable resume가 이 값을 복원해
    # "재시작으로 권한이 확대되지 않는다"는 invariant를 지킨다. 기본 False(안전).
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    # 이 세션의 모델 티어(사용자가 정한 것). durable resume가 이 값을 복원해
    # 재시작 후에도 같은 모델 정책으로 이어간다. 기본 "auto".
    model_tier: Mapped[str] = mapped_column(String, default="auto")
    # 컨텍스트 압축 요약과 그것이 덮는 메시지 수. 메모리에만 두면 run이 끝날 때마다
    # 사라져 다음 run이 전체 히스토리를 다시 보낸다(압축이 영원히 누적되지 않는다).
    compact_summary: Mapped[str] = mapped_column(Text, default="")
    compact_covered: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"))
    git_sha: Mapped[str] = mapped_column(String, default="")
    step_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    thinking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning_effort: Mapped[str] = mapped_column(String, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_miss_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 작업 단위 성능 계측 — role 실행 1회당 집계.
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    compactions: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    selected_skill_count: Mapped[int] = mapped_column(Integer, default=0)
    selected_skills: Mapped[str] = mapped_column(String, default="")
    # RTK식 gain — 도구 결과 압축 전/후 추정 토큰(절감량 측정).
    tool_raw_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_visible_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"))
    title: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="todo")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AcceptanceGate(Base):
    """Acceptance Gate Ledger — 사용자 요구사항을 구현 전에 분해한 검증 가능한 gate.

    passed/failed/unavailable은 프로세스(검증 실행)만 설정한다. 모델은 pending/working/
    blocked/abandoned/unavailable(선언)까지만 쓴다 — self-grading 방지가 이 표의 핵심.
    evidence는 프로세스가 실제 실행한 command/exit_code/output을 JSON으로 기록한다.
    """
    __tablename__ = "acceptance_gates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"))
    title: Mapped[str] = mapped_column(String, default="")          # 요구사항 (예: "로그인")
    description: Mapped[str] = mapped_column(Text, default="")      # 요구사항 상세
    # 실행 가능한 검증 — cwd=workspace에서 sh -c로 실행. observable behavior로 변환할 것.
    verification_method: Mapped[str] = mapped_column(Text, default="")
    expected_result: Mapped[str] = mapped_column(String, default="")  # stdout에서 찾을 문자열(통과 조건)
    # pending | working | passed | failed | unavailable | blocked | abandoned
    status: Mapped[str] = mapped_column(String, default="pending")
    evidence: Mapped[str] = mapped_column(Text, default="{}")       # JSON — process-owned
    failure_reason: Mapped[str] = mapped_column(Text, default="")   # blocked/abandoned/unavailable 사유
    # Task IR requirement 참조(Phase 1, 하위호환). 빈 문자열이면 미연결 — 기존 gate와 완전 호환.
    requirement_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PushDevice(Base):
    __tablename__ = "push_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, default="")
    endpoint: Mapped[str] = mapped_column(Text, default="")  # 구독 고유 식별(중복 방지)
    subscription_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    workspace_path: Mapped[str] = mapped_column(String, default="")
    session_id: Mapped[str] = mapped_column(String, default="")
    timezone: Mapped[str] = mapped_column(String, default="Asia/Seoul")
    # next_run_at(UTC)이 authoritative — 서버 재시작 후 이걸로 복원한다.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recurrence: Mapped[str] = mapped_column(String, default="")        # "" | daily | interval
    recurrence_value: Mapped[str] = mapped_column(String, default="")  # daily "HH:MM"(local) | interval 분
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String, default="scheduled")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str] = mapped_column(Text, default="")
    # retry — 실패 시 재시도 정책. max_retries=0이면 재시도 없음.
    retries: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Refinement(Base):
    """RefinementCandidate — 실행 근거에서 뽑은 작은 개선 후보(자동 적용 안 함).

    승인 전에는 아무것도 바뀌지 않는다. before_text/after_text를 함께 저장해
    나중에 적용하더라도 rollback이 가능하게 한다(prompt drift 방지).
    """
    __tablename__ = "refinements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, default="")
    type: Mapped[str] = mapped_column(String, default="skill")        # skill | supplement
    scope: Mapped[str] = mapped_column(String, default="project")     # project | global
    target: Mapped[str] = mapped_column(String, default="")           # skill 이름 등 적용 대상
    proposed_change: Mapped[str] = mapped_column(Text, default="")
    before_text: Mapped[str] = mapped_column(Text, default="")
    after_text: Mapped[str] = mapped_column(Text, default="")
    evidence_runs: Mapped[str] = mapped_column(Text, default="[]")    # JSON list — 근거 run
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")    # 검증·수리·비용 근거
    failure_pattern: Mapped[str] = mapped_column(String, default="")
    expected_effect: Mapped[str] = mapped_column(String, default="")
    # pending → approved | ignored, rollback은 다시 pending으로 되돌린다.
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Approval(Base):
    """Durable Approval — 승인 상태의 authoritative store.

    메모리의 pending_approvals(Future)는 실행 대기·실시간 UX에만 쓰고, 승인 사실·상태·감사
    정보는 여기에 영속화한다. 서버 재시작 후에도 requested 승인을 복원하고, 승인 후 실제 실행
    직전 args_hash를 재검증해 변조를 막으며, consumed로 중복 실행을 방지한다.
    상태: requested → approved | rejected | expired | cancelled → consumed
    """
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"))
    run_id: Mapped[str] = mapped_column(String, default="")
    tool_name: Mapped[str] = mapped_column(String, default="")
    # 정규화된 tool args의 sha256 — 실행 직전 재검증해 승인 후 args 변조를 차단한다.
    args_hash: Mapped[str] = mapped_column(String, default="")
    # 무엇을 승인하는지 보여줄 안전 축약(원문·전체 args가 아니라 제한된 미리보기).
    preview: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="requested")
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String, default="")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    meta: Mapped[str] = mapped_column(Text, default="{}")  # audit metadata(JSON)


class ToolLedger(Base):
    """side-effect 도구 실행 장부 — resume이 이미 실행된 부작용을 다시 실행하지 않게.

    history 즉시 저장이 재실행 창을 거의 닫았지만, 도구 실행 완료와 저장 사이의 극소 구간이
    남는다. 그 사이에 프로세스가 죽으면 history에는 흔적이 없고 부작용만 디스크·git에 남는다
    (write 중복·bash 재실행·중복 커밋). 그래서 실행 **전에** started를 적고 history 저장 뒤에
    completed로 닫는다. started인 채 남은 행 = "실행됐는지 알 수 없음"이고, 이 상태에서는
    같은 (tool, args)를 자동 재실행하지 않는다 — 모르는 것을 실행하는 것이 가장 위험하다.
    """
    __tablename__ = "tool_ledger"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid hex
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"))
    run_id: Mapped[str] = mapped_column(String, default="")
    tool_name: Mapped[str] = mapped_column(String, default="")
    args_hash: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="started")  # started | completed
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
