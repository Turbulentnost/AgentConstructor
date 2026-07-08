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

    @model_validator(mode="before")
    @classmethod
    def normalize_step_payload(cls, value: object) -> object:
        """Принять частые LLM-синонимы полей шага."""
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if "step_type" not in normalized and "type" in normalized:
            normalized["step_type"] = normalized.pop("type")
        if "step_id" not in normalized and "id" in normalized:
            normalized["step_id"] = normalized.pop("id")
        if "tool_name" not in normalized and "tool" in normalized:
            normalized["tool_name"] = normalized.pop("tool")
        return normalized

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
    complexity: str = "medium"

    @field_validator("complexity", mode="before")
    @classmethod
    def normalize_complexity(cls, value: object) -> str:
        """Привести сложность к low/medium/high, иначе medium."""
        text = str(value or "").strip().lower()
        if text in {"low", "простой", "простая", "низкая", "low complexity"}:
            return "low"
        if text in {"high", "сложный", "сложная", "высокая", "high complexity"}:
            return "high"
        return "medium"

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

