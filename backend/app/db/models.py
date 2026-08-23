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
