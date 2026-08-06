"""Pydantic-модели безопасного LLM planner-слоя."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError


class LLMImageContent(BaseModel):
    """Изображение (например скриншот), передаваемое LLM для анализа UI."""

    base64_data: str
    media_type: str = "image/png"

    @field_validator("base64_data")
    @classmethod
    def validate_base64_data(cls, value: str) -> str:
        """Проверить, что base64-данные изображения заполнены."""
        if not value.strip():
            raise ValueError("base64_data изображения не должен быть пустым")
        return value


class LLMMessage(BaseModel):
    """Одно сообщение chat completion, опционально с изображениями (multimodal)."""

    role: Literal["system", "user", "assistant"]
    content: str
    images: list[LLMImageContent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_content_or_images(self) -> LLMMessage:
        """Content обязателен, если нет изображений; иначе допускается пустой текст."""
        if not self.content.strip() and not self.images:
            raise ValueError("content не должен быть пустым без изображений")
        return self


class LLMRequest(BaseModel):
    """Запрос к OpenAI-compatible chat completion API."""

    messages: list[LLMMessage] = Field(min_length=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    model_name: str
    response_format: str | None = None
    max_tokens: int | None = Field(default=None, gt=0)

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        """Проверить, что model_name заполнен."""
        if not value.strip():
            raise ValueError("model_name не должен быть пустым")
        return value


class LLMResponse(BaseModel):
    """Ответ LLM-клиента."""

    content: str
    raw: dict[str, Any] | None = None
    # OpenAI: choices[0].finish_reason; Anthropic: stop_reason.
    # "length" / "max_tokens" означают, что ответ обрезан по лимиту токенов.
    finish_reason: str | None = None


class ToolSelectionItem(BaseModel):
    """Один выбранный LLM planner-ом tool_name из ToolsCatalog."""

    tool_name: str
    reason: str
    required: bool

    @field_validator("tool_name", "reason")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что текстовые поля заполнены."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value


class LLMPlanningResult(BaseModel):
    """Структурированный результат LLM planner-а."""

    understood_goal: str
    selected_tools: list[ToolSelectionItem]
    missing_data: list[str]
    needs_human: bool
    needs_human_reason: str | None
    needs_human_or_new_tool: bool = False
    warnings: list[str] = Field(default_factory=list)

    @field_validator("understood_goal")
    @classmethod
    def validate_understood_goal(cls, value: str) -> str:
        """Проверить, что understood_goal заполнен."""
        if not value.strip():
            raise ValueError("understood_goal не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_human_reason(self) -> LLMPlanningResult:
        """Если нужен человек, причина должна быть заполнена."""
        if self.needs_human:
            if self.needs_human_reason is None or not self.needs_human_reason.strip():
                raise ValueError(
                    "Если needs_human=True, needs_human_reason должен быть заполнен"
                )
        return self


def parse_planning_result(content: str) -> LLMPlanningResult:
    """Распарсить JSON LLM planner-а и провалидировать его схему."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMInvalidJSONError(f"LLM вернула невалидный JSON: {exc.msg}") from exc

    try:
        return LLMPlanningResult.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidJSONError(
            f"JSON LLM не соответствует схеме LLMPlanningResult: {exc}"
        ) from exc

