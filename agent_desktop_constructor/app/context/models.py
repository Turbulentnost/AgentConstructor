"""Pydantic-модели контекста агента.

Контекст хранится в `AgentRuntimeState.variables["context_snapshot"]`, поэтому
все модели должны быть JSON-совместимыми и компактными.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


CONTEXT_SNAPSHOT_VERSION = 1


class ContextSection(StrEnum):
    """Разделы контекста агента."""

    CREATION = "creation"
    RUN = "run"
    EVENTS = "events"
    TOOL_RESULTS = "tool_results"
    PAUSE = "pause"
    AGENT_CALL = "agent_call"
    USER_HISTORY = "user_history"
    PERSISTENT = "persistent"
    TEMPORARY = "temporary"


class ContextEntry(BaseModel):
    """Одна запись контекста внутри раздела."""

    key: str
    value: object
    summary: str | None = None
    priority: int = Field(default=50, ge=0, le=100)
    size_chars: int = Field(default=0, ge=0)
    truncated: bool = False

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        """Проверить, что ключ контекста заполнен."""
        if not value.strip():
            raise ValueError("key не должен быть пустым")
        return value


class ContextBudget(BaseModel):
    """Ограничения размера контекста."""

    max_total_chars: int = Field(default=24_000, gt=0)
    max_entry_chars: int = Field(default=3_000, gt=0)
    section_limits: dict[ContextSection, int] = Field(
        default_factory=lambda: {
            ContextSection.CREATION: 3_000,
            ContextSection.RUN: 4_000,
            ContextSection.EVENTS: 3_000,
            ContextSection.TOOL_RESULTS: 7_000,
            ContextSection.PAUSE: 2_500,
            ContextSection.AGENT_CALL: 2_000,
            ContextSection.USER_HISTORY: 3_000,
            ContextSection.PERSISTENT: 4_000,
            ContextSection.TEMPORARY: 3_000,
        }
    )

    def limit_for(self, section: ContextSection) -> int:
        """Вернуть лимит символов для раздела."""
        return self.section_limits.get(section, self.max_total_chars)


class ContextUsage(BaseModel):
    """Использование бюджета контекста."""

    total_chars: int = 0
    total_limit: int
    total_percent: float = 0.0
    section_chars: dict[ContextSection, int] = Field(default_factory=dict)
    section_percent: dict[ContextSection, float] = Field(default_factory=dict)


class AgentContextSnapshot(BaseModel):
    """Сериализуемый снимок контекста агента."""

    version: int = CONTEXT_SNAPSHOT_VERSION
    sections: dict[ContextSection, list[ContextEntry]] = Field(default_factory=dict)
    usage: ContextUsage | None = None

    def entries(self, section: ContextSection) -> list[ContextEntry]:
        """Вернуть записи раздела."""
        return self.sections.setdefault(section, [])
