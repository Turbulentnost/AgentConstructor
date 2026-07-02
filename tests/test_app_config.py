"""Тесты AppConfig и загрузки конфигурации из окружения."""

from pathlib import Path

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import (
    AppConfig,
    load_app_config_from_env,
    load_dotenv_into_environ,
)


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать LLM-ключи и явный provider из окружения."""
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_API_KEY_CLAUDE",
        "AGENT_APP_LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


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


def test_claude_key_selects_anthropic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """При наличии ключа Claude выбирается anthropic и включается planner."""
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY_CLAUDE", "sk-ant-test")

    config = load_app_config_from_env()

    assert config.llm_provider == "anthropic"
    assert config.llm_base_url == "https://api.anthropic.com"
    assert config.llm_model_name == "claude-sonnet-4-6"
    assert config.llm_api_key == "sk-ant-test"
    assert config.use_llm_planner is True


def test_openai_key_selects_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без Claude, но с OpenAI-ключом выбирается openai_compatible."""
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")

    config = load_app_config_from_env()

    assert config.llm_provider == "openai_compatible"
    assert config.llm_base_url == "https://api.openai.com"
    assert config.llm_model_name == "gpt-4o-mini"
    assert config.llm_api_key == "sk-openai-test"
    assert config.use_llm_planner is True


def test_no_keys_keeps_lm_studio_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без ключей остаётся локальный LM Studio по умолчанию."""
    _clear_llm_env(monkeypatch)

    config = load_app_config_from_env()

    assert config.llm_provider == "openai_compatible"
    assert config.llm_base_url == "http://192.168.1.157:1234"
    assert config.use_llm_planner is False


def test_explicit_provider_overrides_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Явный AGENT_APP_LLM_PROVIDER имеет приоритет над авто-выбором."""
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY_CLAUDE", "sk-ant-test")
    monkeypatch.setenv("AGENT_APP_LLM_PROVIDER", "openai_compatible")

    config = load_app_config_from_env()

    assert config.llm_provider == "openai_compatible"


def test_load_dotenv_does_not_override_existing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """load_dotenv_into_environ не переопределяет уже заданные переменные."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=from-file\nSOME_NEW_VAR=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")
    monkeypatch.delenv("SOME_NEW_VAR", raising=False)

    load_dotenv_into_environ(env_file)

    import os

    assert os.environ["OPENAI_API_KEY"] == "already-set"
    assert os.environ["SOME_NEW_VAR"] == "file-value"

