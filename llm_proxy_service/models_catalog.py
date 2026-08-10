"""ORM-модели каталога опубликованных агентов, pins и сводок запусков."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from llm_proxy_service.models_user import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


VISIBILITY_PRIVATE = "private"
VISIBILITY_DEPARTMENT = "department"
VISIBILITY_ALL = "all"
VISIBILITY_SELECTED = "selected"
VALID_VISIBILITIES = frozenset(
    {
        VISIBILITY_PRIVATE,
        VISIBILITY_DEPARTMENT,
        VISIBILITY_ALL,
        VISIBILITY_SELECTED,
    }
)


class SharedAgentEntity(Base):
    """Опубликованный агент в общем каталоге Postgres."""

    __tablename__ = "shared_agents"

    agent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_onec_uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_department: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    short_description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    image_object_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    agent_spec_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default=VISIBILITY_PRIVATE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SharedAgentDepartmentEntity(Base):
    """Отделы с доступом к агенту при visibility=selected."""

    __tablename__ = "shared_agents_departments"
    __table_args__ = (
        UniqueConstraint("agent_id", "department", name="uq_shared_agent_department"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("shared_agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department: Mapped[str] = mapped_column(String(256), nullable=False, default="")


class UserAgentPinEntity(Base):
    """Закрепление агента на Главной у пользователя."""

    __tablename__ = "user_agent_pins"
    __table_args__ = (
        UniqueConstraint("onec_uid", "agent_id", name="uq_user_agent_pin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onec_uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("shared_agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pinned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentRunSummaryEntity(Base):
    """Краткая сводка запуска для раздела «Мои задания»."""

    __tablename__ = "agent_run_summaries"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    onec_uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
