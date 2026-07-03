"""Тесты конфигурации LLM-прокси и маршрутизации приложения через прокси."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.app.core.config import AppConfig
from llm_proxy_service.config import load_proxy_config


def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать все LLM_PROXY_*/OPENAI_API_KEY* переменные из окружения."""
    for key in list(__import__("os").environ):
        if key.startswith("LLM_PROXY_") or key.startswith("OPENAI_API_KEY"):
            monkeypatch.delenv(key, raising=False)


def test_default_chain_order_is_codex_chatgpt_lmstudio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """По умолчанию цепочка идёт Codex(Sonnet) -> ChatGPT -> LM Studio."""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY_CLAUDE", "sk-ant-test")

    config = load_proxy_config()

    names = [backend.name for backend in config.chain]
    assert names == ["codex", "chatgpt", "lmstudio"]
    # Слот codex настроен на Claude Sonnet (anthropic style).
    assert config.chain[0].style == "anthropic"
    assert config.chain[0].base_url == "https://api.anthropic.com"
    assert config.chain[0].model == "claude-sonnet-4-6"
    assert config.chain[0].api_key == "sk-ant-test"
    assert config.chain[1].api_key == "sk-test"
    assert config.chain[2].api_key is None
    assert config.chain[2].base_url == "http://192.168.1.157:1234"


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
        llm_provider="anthropic",
        llm_base_url="https://api.anthropic.com",
        llm_model_name="claude-sonnet-4-6",
        llm_api_key="sk-secret",
        llm_proxy_url="http://192.168.2.135:8080",
    )

    llm_config = config.to_llm_config()

    assert llm_config.provider == "openai_compatible"
    assert llm_config.base_url == "http://192.168.2.135:8080"
    assert llm_config.api_key is None
    assert llm_config.model_name == "claude-sonnet-4-6"


def test_app_config_direct_when_proxy_absent() -> None:
    """Без llm_proxy_url поведение прежнее: напрямую к провайдеру."""
    config = AppConfig(
        llm_provider="anthropic",
        llm_base_url="https://api.anthropic.com",
        llm_model_name="claude-sonnet-4-6",
        llm_api_key="sk-secret",
    )

    llm_config = config.to_llm_config()

    assert llm_config.provider == "anthropic"
    assert llm_config.base_url == "https://api.anthropic.com"
    assert llm_config.api_key == "sk-secret"
