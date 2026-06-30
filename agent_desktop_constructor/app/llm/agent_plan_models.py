"""Модели LLM-плана агента, из которого Builder собирает AgentSpec."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class LLMPlannedTool(BaseModel):
    """Tool, выбранный LLM из ToolsCatalog."""

    tool_name: str
    reason: str
    required: bool = True

    @field_validator("tool_name", "reason")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что строковое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value


class LLMPlannedStep(BaseModel):
    """Шаг плана агента."""

    step_id: str
    step_type: str
    title: str
    description: str
    tool_name: str | None = None
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("step_id", "step_type", "title", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что строковое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @field_validator("tool_name")
    @classmethod
    def validate_optional_tool_name(cls, value: str | None) -> str | None:
        """Если tool_name указан, он не должен быть пустым."""
        if value is not None and not value.strip():
            raise ValueError("tool_name не должен быть пустым")
        return value


class LLMAgentPlan(BaseModel):
    """План агента, возвращаемый LLM Planner-ом."""

    agent_name: str
    goal: str
    selected_tools: list[LLMPlannedTool]
    steps: list[LLMPlannedStep]
    missing_data: list[str] = Field(default_factory=list)
    needs_human: bool = False
    warnings: list[str] = Field(default_factory=list)

    @field_validator("agent_name", "goal")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить обязательные текстовые поля."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @model_validator(mode="after")
    def validate_step_ids_unique(self) -> LLMAgentPlan:
        """Проверить уникальность step_id."""
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id в LLMAgentPlan должны быть уникальными")
        return self

