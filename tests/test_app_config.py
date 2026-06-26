"""Тесты AppConfig и загрузки конфигурации из окружения."""

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import (
    AppConfig,
    load_app_config_from_env,
)


def test_app_config_uses_defaults() -> None:
    """AppConfig создаётся со значениями по умолчанию."""
    config = AppConfig()

    assert config.app_name == "Конструктор ИИ-агентов"
    assert config.database_path == "./data/agents.db"


def test_default_run_mode_is_fake() -> None:
    """По умолчанию run_mode == fake."""
    assert AppConfig().run_mode == AppRunMode.FAKE


def test_to_llm_config_returns_default_base_url() -> None:
    """to_llm_config возвращает default base_url."""
    assert AppConfig().to_llm_config().base_url == "http://192.168.1.157:1234"


def test_to_llm_config_returns_default_model_name() -> None:
    """to_llm_config возвращает default model_name."""
    assert AppConfig().to_llm_config().model_name == "openai/gpt-oss-120b"


def test_load_app_config_from_env_reads_run_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_app_config_from_env читает AGENT_APP_RUN_MODE."""
    monkeypatch.setenv("AGENT_APP_RUN_MODE", "outlook_readonly")

    config = load_app_config_from_env()

    assert config.run_mode == AppRunMode.OUTLOOK_READONLY


@pytest.mark.parametrize("value", ["1", "true", "yes", "да"])
def test_load_app_config_from_env_reads_boolean(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """Boolean env читается из разрешённых truthy-значений."""
    monkeypatch.setenv("AGENT_APP_USE_LLM_PLANNER", value)

    config = load_app_config_from_env()

    assert config.use_llm_planner is True


def test_invalid_run_mode_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Некорректный run_mode вызывает понятную ошибку."""
    monkeypatch.setenv("AGENT_APP_RUN_MODE", "bad-mode")

    with pytest.raises(ValueError, match="AGENT_APP_RUN_MODE"):
        load_app_config_from_env()

