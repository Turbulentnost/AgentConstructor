"""LLM-клиент с автоматическим переключением на запасной backend."""

from __future__ import annotations

from agent_desktop_constructor.app.llm.errors import (
    LLMConnectionError,
    LLMResponseError,
)
from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.core.models.llm_config import LLMConfig


class FallbackLLMClient:
    """Сначала вызывает основной LLM-клиент, затем запасной при endpoint-сбое."""

    def __init__(self, primary_client, fallback_client) -> None:
        """Сохранить основной и запасной клиенты."""
        self._primary_client = primary_client
        self._fallback_client = fallback_client

    @property
    def config(self) -> LLMConfig:
        """Вернуть конфигурацию основного клиента для существующих prompt-builder-ов."""
        return self._primary_client.config

    @property
    def fallback_config(self) -> LLMConfig:
        """Вернуть конфигурацию запасного клиента для диагностики."""
        return self._fallback_client.config

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        """Выполнить запрос с автоматическим fallback на LM Studio."""
        try:
            return self._primary_client.complete(llm_request)
        except (LLMConnectionError, LLMResponseError) as primary_exc:
            fallback_request = llm_request.model_copy(
                update={"model_name": self._fallback_client.config.model_name}
            )
            try:
                response = self._fallback_client.complete(fallback_request)
            except (LLMConnectionError, LLMResponseError) as fallback_exc:
                raise _combine_errors(primary_exc, fallback_exc) from fallback_exc
            return response


def _combine_errors(
    primary_exc: LLMConnectionError | LLMResponseError,
    fallback_exc: LLMConnectionError | LLMResponseError,
) -> LLMConnectionError | LLMResponseError:
    """Собрать понятную ошибку, если основной и запасной endpoint недоступны."""
    message = (
        "Основной LLM endpoint недоступен, fallback на LM Studio тоже не сработал. "
        f"Основная ошибка: {primary_exc}. "
        f"Ошибка LM Studio: {fallback_exc}"
    )
    if isinstance(fallback_exc, LLMConnectionError):
        return LLMConnectionError(message)
    return LLMResponseError(message)
