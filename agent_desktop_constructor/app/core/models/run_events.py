"""Модели журнала событий выполнения агента."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class AgentRunEventType(StrEnum):
    """Тип события выполнения агента."""

    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    HUMAN_APPROVAL_REQUESTED = "human_approval_requested"
    HUMAN_APPROVAL_ANSWERED = "human_approval_answered"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    CHECKPOINT_SAVED = "checkpoint_saved"


class AgentRunEvent(BaseModel):
    """Структурированное событие выполнения агента."""

    event_id: str
    run_id: str
    event_type: AgentRunEventType
    node_id: str | None = None
    tool_name: str | None = None
    message: str
    details: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("event_id", "run_id", "message")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательные текстовые поля заполнены."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

