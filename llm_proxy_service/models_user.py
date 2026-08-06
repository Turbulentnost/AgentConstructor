"""ORM-модель пользователя системы (синхронизация из 1С)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """База декларативных моделей llm_proxy_service."""


class UserEntity(Base):
    """Локальный пользователь: FIO/department из 1С, email/avatar — свои."""

    __tablename__ = "app_users"

    onec_uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    login: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    password_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    avatar_object_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
