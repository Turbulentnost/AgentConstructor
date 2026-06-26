"""Конфигурация локальной OpenAI-compatible языковой модели."""

from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    """Настройки LLM, которую позже будет использовать Agent Builder."""

    provider: str = "openai_compatible"
    base_url: str = "http://192.168.1.157:1234"
    model_name: str = "openai/gpt-oss-120b"
    temperature: float = Field(default=0.2, ge=0, le=2)
    timeout_seconds: int = Field(default=120, gt=0)

    @field_validator("base_url", "model_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательные настройки LLM заполнены."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value
