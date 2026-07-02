"""Anthropic (Claude) LLM client с интерфейсом OpenAI-compatible клиента."""

from __future__ import annotations

import json
from urllib import error, request

from agent_desktop_constructor.app.llm.client import _read_http_error_body
from agent_desktop_constructor.app.llm.errors import (
    LLMConnectionError,
    LLMResponseError,
)
from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.core.models.llm_config import LLMConfig

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicLLMClient:
    """HTTP-клиент Anthropic Messages API с тем же контрактом, что OpenAI-клиент."""

    def __init__(self, config: LLMConfig) -> None:
        """Сохранить конфигурацию Claude."""
        self._config = config

    @property
    def config(self) -> LLMConfig:
        """Вернуть конфигурацию клиента для сборки LLMRequest."""
        return self._config

    def complete(self, llm_request: LLMRequest) -> LLMResponse:
        """Выполнить messages-запрос Claude и вернуть текст ответа."""
        endpoint = self._build_endpoint()
        payload = self._build_payload(llm_request)
        try:
            raw_bytes = self._post_payload(endpoint, payload)
        except error.HTTPError as exc:
            details = _read_http_error_body(exc)
            message = f"LLM endpoint вернул HTTP {exc.code}"
            if details:
                message += f": {details}"
            raise LLMResponseError(message) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise LLMConnectionError(
                f"Не удалось подключиться к LLM endpoint: {exc}"
            ) from exc

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
        with request.urlopen(
            http_request,
            timeout=self._config.timeout_seconds,
        ) as response:
            return response.read()

    def _build_headers(self) -> dict[str, str]:
        """Собрать заголовки Anthropic Messages API."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._config.api_key:
            headers["x-api-key"] = self._config.api_key
        return headers

    def _build_endpoint(self) -> str:
        """Собрать URL /v1/messages."""
        return self._config.base_url.rstrip("/") + "/v1/messages"

    def _build_payload(self, llm_request: LLMRequest) -> dict:
        """Собрать payload Anthropic: system отдельно от messages."""
        system_parts = [
            message.content
            for message in llm_request.messages
            if message.role == "system"
        ]
        conversation = [
            {"role": message.role, "content": message.content}
            for message in llm_request.messages
            if message.role != "system"
        ]
        payload: dict = {
            "model": llm_request.model_name,
            "max_tokens": self._config.max_tokens,
            "temperature": llm_request.temperature,
            "messages": conversation,
        }
        if system_parts:
            system_prompt = "\n\n".join(system_parts)
            if llm_request.response_format == "json_object":
                system_prompt += (
                    "\n\nВерни ответ строго как один JSON-объект без Markdown и пояснений."
                )
            payload["system"] = system_prompt
        return payload

    def _extract_content(self, raw_payload: dict) -> str:
        """Достать текст из content[].text Anthropic-ответа."""
        try:
            blocks = raw_payload["content"]
        except (KeyError, TypeError) as exc:
            raise LLMResponseError(
                "Anthropic endpoint вернул ответ без поля content"
            ) from exc

        if not isinstance(blocks, list) or not blocks:
            raise LLMResponseError("Anthropic endpoint вернул пустой content")

        text_parts = [
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "".join(text_parts).strip()
        if not content:
            raise LLMResponseError("Anthropic endpoint вернул content без текста")
        return _strip_markdown_fences(content)


def _strip_markdown_fences(content: str) -> str:
    """Убрать ```json/``` обёртку, если модель вернула JSON в code block."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
