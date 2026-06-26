"""Тесты конфигурации локальной LLM."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.core.models.llm_config import LLMConfig


def test_llm_config_uses_default_values() -> None:
    """LLMConfig создается со значениями по умолчанию."""
    config = LLMConfig()

    assert config.provider == "openai_compatible"
    assert config.temperature == 0.2
    assert config.timeout_seconds == 120


def test_default_base_url_matches_local_model_endpoint() -> None:
    """base_url по умолчанию указывает на локальный OpenAI-compatible endpoint."""
    config = LLMConfig()

    assert config.base_url == "http://192.168.1.157:1234"


def test_default_model_name_matches_local_model() -> None:
    """model_name по умолчанию указывает на локальную модель."""
    config = LLMConfig()

    assert config.model_name == "openai/gpt-oss-120b"


def test_empty_base_url_raises_error() -> None:
    """Пустой base_url вызывает ошибку валидации."""
    with pytest.raises(ValidationError, match="base_url"):
        LLMConfig(base_url="")


def test_empty_model_name_raises_error() -> None:
    """Пустой model_name вызывает ошибку валидации."""
    with pytest.raises(ValidationError, match="model_name"):
        LLMConfig(model_name="")


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_invalid_temperature_raises_error(temperature: float) -> None:
    """Некорректная temperature вызывает ошибку валидации."""
    with pytest.raises(ValidationError):
        LLMConfig(temperature=temperature)


@pytest.mark.parametrize("timeout_seconds", [0, -1])
def test_non_positive_timeout_seconds_raises_error(timeout_seconds: int) -> None:
    """timeout_seconds меньше или равный нулю вызывает ошибку валидации."""
    with pytest.raises(ValidationError):
        LLMConfig(timeout_seconds=timeout_seconds)
