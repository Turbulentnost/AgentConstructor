"""Фабрика LLM-клиентов по провайдеру из LLMConfig."""

from __future__ import annotations

from agent_desktop_constructor.app.llm.anthropic_client import AnthropicLLMClient
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.fallback_client import FallbackLLMClient
from agent_desktop_constructor.core.models.llm_config import LLMConfig

ANTHROPIC_PROVIDERS = {"anthropic", "claude"}
LM_STUDIO_BASE_URL = "http://192.168.1.157:1234"
LM_STUDIO_MODEL = "openai/gpt-oss-120b"


def build_llm_client(config: LLMConfig):
    """Вернуть LLM-клиент, соответствующий config.provider.

    Оба клиента реализуют одинаковый контракт (`complete`, `config`),
    поэтому вызывающий код не зависит от конкретного провайдера.
    """
    provider = (config.provider or "").strip().casefold()
    if provider in ANTHROPIC_PROVIDERS:
        return FallbackLLMClient(
            AnthropicLLMClient(config),
            OpenAICompatibleLLMClient(_build_lm_studio_fallback_config(config)),
        )
    return OpenAICompatibleLLMClient(config)


def _build_lm_studio_fallback_config(primary_config: LLMConfig) -> LLMConfig:
    """Собрать запасную конфигурацию LM Studio для Claude/Sonnet fallback."""
    return LLMConfig(
        provider="openai_compatible",
        base_url=LM_STUDIO_BASE_URL,
        model_name=LM_STUDIO_MODEL,
        api_key=None,
        temperature=primary_config.temperature,
        timeout_seconds=primary_config.timeout_seconds,
        max_tokens=primary_config.max_tokens,
    )
