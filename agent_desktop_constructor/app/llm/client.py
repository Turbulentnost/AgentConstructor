"""OpenAI-compatible LLM client для локальной модели."""

from __future__ import annotations

import json
from urllib import error, request

from agent_desktop_constructor.app.llm.errors import (
    LLMConnectionError,
    LLMResponseError,
)
from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.core.models.llm_config import LLMConfig


class OpenAICompatibleLLMClient:
    """Минимальный HTTP-клиент для OpenAI-compatible chat completions API."""

    def __init__(self, config: LLMConfig) -> None:
        """Сохранить конфигурацию локальной LLM."""
        self._config = config

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        """Выполнить chat completion запрос и вернуть текст ответа."""
        endpoint = self._build_endpoint()
        payload = self._build_payload(llm_request)
        http_request = request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self._config.timeout_seconds,
            ) as response:
                raw_bytes = response.read()
        except error.HTTPError as exc:
            raise LLMResponseError(f"LLM endpoint вернул HTTP {exc.code}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise LLMConnectionError(f"Не удалось подключиться к LLM endpoint: {exc}") from exc

        try:
            raw_payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMResponseError("LLM endpoint вернул невалидный JSON") from exc

        content = self._extract_content(raw_payload)
        return LLMResponse(content=content, raw=raw_payload)

    def _build_endpoint(self) -> str:
        """Собрать URL /v1/chat/completions."""
        return self._config.base_url.rstrip("/") + "/v1/chat/completions"

    def _build_payload(self, llm_request: LLMRequest) -> dict:
        """Собрать OpenAI-compatible JSON payload."""
        payload = {
            "model": llm_request.model_name,
            "messages": [
                message.model_dump(mode="json") for message in llm_request.messages
            ],
            "temperature": llm_request.temperature,
        }
        if llm_request.response_format is not None:
            payload["response_format"] = {"type": llm_request.response_format}
        return payload

    def _extract_content(self, raw_payload: dict) -> str:
        """Достать choices[0].message.content из ответа."""
        try:
            content = raw_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                "LLM endpoint вернул ответ без choices[0].message.content"
            ) from exc

        if not isinstance(content, str):
            raise LLMResponseError("LLM endpoint вернул content не строкой")
        return content

