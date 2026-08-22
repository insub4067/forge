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
    status: Mapped[str] = mapped_column(String, default="active")
    model: Mapped[str] = mapped_column(String, default="")
    logical_budget: Mapped[int] = mapped_column(Integer, default=262144)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # run이 실행 중인지 영속화한다 — 서버 재시작으로 중단된 run을 시작 시 감지하기 위함.
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    # 마지막 run의 종료 상태 — 성공 정의(completed)와 세션 집계의 기준.
    final_status: Mapped[str] = mapped_column(String, default="")
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VisionAnalysis(Base):
    __tablename__ = "vision_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, default="")
    task_id: Mapped[str] = mapped_column(String, default="")
    image_path: Mapped[str] = mapped_column(String, default="")
    analysis_result: Mapped[str] = mapped_column(Text, default="")
    issues: Mapped[str] = mapped_column(Text, default="")
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
