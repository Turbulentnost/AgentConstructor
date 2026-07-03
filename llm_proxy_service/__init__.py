"""Асинхронный LLM-прокси (FastAPI) с цепочкой fallback: Codex -> ChatGPT -> LM Studio.

Сервис разворачивается на машине с VPN-доступом к LLM и предоставляет
OpenAI-compatible endpoint ``/v1/chat/completions``. Остальные ПК (без VPN)
обращаются к этому сервису, а он последовательно пробует настроенные upstream-LLM
и возвращает первый успешный ответ в едином OpenAI-формате.
"""
