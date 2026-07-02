"""Фабрика LLM-клиентов по провайдеру из LLMConfig."""

from __future__ import annotations

from agent_desktop_constructor.app.llm.anthropic_client import AnthropicLLMClient
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.core.models.llm_config import LLMConfig

ANTHROPIC_PROVIDERS = {"anthropic", "claude"}


def build_llm_client(config: LLMConfig):
    """Вернуть LLM-клиент, соответствующий config.provider.

    Оба клиента реализуют одинаковый контракт (`complete`, `config`),
    поэтому вызывающий код не зависит от конкретного провайдера.
    """
    provider = (config.provider or "").strip().casefold()
    if provider in ANTHROPIC_PROVIDERS:
        return AnthropicLLMClient(config)
    return OpenAICompatibleLLMClient(config)
