"""OpenAI-compatible LLM client для локальной модели."""

from __future__ import annotations

import json
from urllib import error, request

from agent_desktop_constructor.app.llm.errors import (
    LLMConnectionError,
    LLMResponseError,
)
from agent_desktop_constructor.app.llm.http_retry import read_with_retry
from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.core.models.llm_config import LLMConfig


class OpenAICompatibleLLMClient:
    """Минимальный HTTP-клиент для OpenAI-compatible chat completions API."""

    def __init__(self, config: LLMConfig) -> None:
        """Сохранить конфигурацию локальной LLM."""
        self._config = config

    @property
    def config(self) -> LLMConfig:
        """Вернуть конфигурацию клиента для сборки LLMRequest."""
        return self._config

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        """Выполнить chat completion запрос и вернуть текст ответа."""
        endpoint = self._build_endpoint()
        payload = self._build_payload(llm_request)
        try:
            raw_bytes = self._post_payload(endpoint, payload)
        except error.HTTPError as exc:
            if exc.code == 400 and llm_request.response_format is not None:
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                try:
                    raw_bytes = self._post_payload(endpoint, fallback_payload)
                except error.HTTPError as retry_exc:
                    self._raise_http_response_error(retry_exc)
            else:
                self._raise_http_response_error(exc)
        except (error.URLError, TimeoutError, OSError) as exc:
            raise LLMConnectionError(f"Не удалось подключиться к LLM endpoint: {exc}") from exc

        try:
            raw_payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMResponseError("LLM endpoint вернул невалидный JSON") from exc

        content = self._extract_content(raw_payload)
        return LLMResponse(content=content, raw=raw_payload)

    def _post_payload(self, endpoint: str, payload: dict) -> bytes:
        """Отправить JSON payload и вернуть raw bytes ответа."""
        http_request = request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )
        return read_with_retry(
            request.urlopen,
            http_request,
            self._config.timeout_seconds,
        )

    def _build_headers(self) -> dict[str, str]:
        """Собрать HTTP-заголовки, добавляя Bearer-авторизацию при наличии ключа."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def _raise_http_response_error(self, exc: error.HTTPError) -> None:
        """Выбросить LLMResponseError с телом HTTP-ответа, если оно доступно."""
        details = _read_http_error_body(exc)
        message = f"LLM endpoint вернул HTTP {exc.code}"
        if details:
            message += f": {details}"
        raise LLMResponseError(message) from exc


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


def _read_http_error_body(exc: error.HTTPError, max_chars: int = 1000) -> str:
    """Безопасно прочитать тело HTTPError для диагностики."""
    try:
        body = exc.read()
    except Exception:
        return ""
    if not body:
        return ""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body)
    return text.strip()[:max_chars]

