"""Исключения LLM-слоя."""


class LLMError(Exception):
    """Базовая ошибка LLM-слоя."""


class LLMConnectionError(LLMError):
    """Ошибка соединения с OpenAI-compatible endpoint."""


class LLMResponseError(LLMError):
    """Некорректный HTTP-ответ или payload LLM."""


class LLMInvalidJSONError(LLMError):
    """LLM вернула невалидный или не соответствующий схеме JSON."""

