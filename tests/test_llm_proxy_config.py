"""Тесты конфигурации LLM-прокси и маршрутизации приложения через прокси."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.app.core.config import AppConfig
from llm_proxy_service.config import load_proxy_config


def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать все LLM_PROXY_*/OPENAI_API_KEY* переменные из окружения."""
    for key in list(__import__("os").environ):
        if (
            key.startswith("LLM_PROXY_")
            or key.startswith("OPENAI_API_KEY")
            or key == "CLAUDE_API_KEY"
        ):
            monkeypatch.delenv(key, raising=False)


def test_default_chain_order_is_chatgpt_claude_lmstudio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """По умолчанию цепочка идёт Chat-GPT 5.5 -> Claude -> LM Studio."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-test")

    config = load_proxy_config()

    names = [backend.name for backend in config.chain]
    assert names == ["chatgpt", "claude", "lmstudio"]
    assert config.chain[0].style == "openai"
    assert config.chain[0].base_url == "https://api.openai.com"
    assert config.chain[0].model == "gpt-5.5"
    assert config.chain[0].api_key == "sk-test"
    assert config.chain[0].supports_reasoning is True
    assert config.chain[1].style == "anthropic"
    assert config.chain[1].base_url == "https://api.claudehub.fun"
    assert config.chain[1].api_key == "sk-ant-test"
    assert config.chain[1].discover_models is True
    assert config.chain[2].api_key is None
    assert config.chain[2].base_url == "http://192.168.1.157:1234"


def test_claude_backend_accepts_legacy_api_key_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude backend читает и новое CLAUDE_API_KEY, и старое OPENAI_API_KEY_CLAUDE."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY_CLAUDE", "sk-ant-legacy")

    config = load_proxy_config()

    claude = next(backend for backend in config.chain if backend.name == "claude")
    assert claude.api_key == "sk-ant-legacy"


def test_claude_models_are_configurable_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback-список Claude-моделей задаётся через LLM_PROXY_CLAUDE_MODELS."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv(
        "LLM_PROXY_CLAUDE_MODELS",
        "claude-a, claude-b",
    )

    config = load_proxy_config()

    claude = next(backend for backend in config.chain if backend.name == "claude")
    assert claude.configured_models == ("claude-a", "claude-b")


def test_claude_base_url_can_use_anthropic_base_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANTHROPIC_BASE_URL переопределяет base_url Claude backend-а."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://custom.example")

    config = load_proxy_config()

    claude = next(backend for backend in config.chain if backend.name == "claude")
    assert claude.base_url == "https://custom.example"


def test_chain_order_and_models_are_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_PROXY_CHAIN и per-backend переменные переопределяют дефолты."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("LLM_PROXY_CHAIN", "lmstudio,chatgpt")
    monkeypatch.setenv("LLM_PROXY_CHATGPT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_PROXY_CHATGPT_API_KEY", "sk-inline")

    config = load_proxy_config()

    names = [backend.name for backend in config.chain]
    assert names == ["lmstudio", "chatgpt"]
    chatgpt = config.chain[1]
    assert chatgpt.model == "gpt-4o-mini"
    assert chatgpt.api_key == "sk-inline"


def test_app_config_routes_through_proxy_when_set() -> None:
    """При заданном llm_proxy_url to_llm_config уводит запросы на прокси."""
    config = AppConfig(
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com",
        llm_model_name="chatgpt:internal",
        llm_api_key="sk-secret",
        llm_proxy_url="http://192.168.2.135:8080",
    )

    llm_config = config.to_llm_config()

    assert llm_config.provider == "openai_compatible"
    assert llm_config.base_url == "http://192.168.2.135:8080"
    assert llm_config.api_key is None
    assert llm_config.model_name == "chatgpt:internal"


def test_app_config_direct_when_proxy_absent() -> None:
    """Без llm_proxy_url поведение прежнее: напрямую к провайдеру."""
    config = AppConfig(
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com",
        llm_model_name="gpt-5.5",
        llm_api_key="sk-secret",
    )

    llm_config = config.to_llm_config()

    assert llm_config.provider == "openai_compatible"
    assert llm_config.base_url == "https://api.openai.com"
    assert llm_config.api_key == "sk-secret"
