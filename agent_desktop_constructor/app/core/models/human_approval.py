"""Модели очереди подтверждений человека."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class HumanApprovalStatus(StrEnum):
    """Статус запроса подтверждения человека."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class HumanApprovalRecord(BaseModel):
    """Запись запроса подтверждения человека, сохранённая отдельно от state."""

    approval_id: str
    run_id: str
    agent_id: str
    node_id: str
    tool_name: str | None = None
    question: str
    options: list[str]
    status: HumanApprovalStatus = HumanApprovalStatus.PENDING
    selected_option: str | None = None
    comment: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    answered_at: datetime | None = None

    @field_validator("approval_id", "run_id", "agent_id", "node_id", "question")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательные текстовые поля заполнены."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        """Проверить, что список вариантов ответа не пустой."""
        if not value:
            raise ValueError("options не должен быть пустым")
        if any(not option.strip() for option in value):
            raise ValueError("options не должен содержать пустые значения")
        return value

    @model_validator(mode="after")
    def validate_answered_at_for_final_answer(self) -> HumanApprovalRecord:
        """Для answered-статусов answered_at должен быть заполнен."""
        if (
            self.status in {HumanApprovalStatus.APPROVED, HumanApprovalStatus.REJECTED}
            and self.answered_at is None
        ):
            raise ValueError("answered_at обязателен для approved/rejected")
        return self

