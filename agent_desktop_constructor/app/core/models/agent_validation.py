"""Модели результата пробной проверки агента."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class AgentValidationStatus(StrEnum):
    """Статус проверки работоспособности агента."""

    NOT_CHECKED = "not_checked"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"
    NEEDS_CREDENTIALS = "needs_credentials"


class AgentValidationResult(BaseModel):
    """Результат валидации AgentSpec и пробного запуска."""

    agent_id: str
    status: AgentValidationStatus
    run_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    critical_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tool_result_checks: list[dict] = Field(default_factory=list)
    summary: str
    final_message: str | None = None
    output_data: dict | None = None
    suggested_fixes: list[str] = Field(default_factory=list)

    @field_validator("agent_id", "summary")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить обязательные текстовые поля."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

