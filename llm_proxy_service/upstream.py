"""Асинхронная отправка запроса в upstream-LLM и приведение ответа к OpenAI-формату.

Вход прокси всегда OpenAI chat/completions. Выход прокси тоже всегда OpenAI-формат
(``choices[0].message.content``), поэтому клиент приложения (OpenAI-compatible)
не зависит от того, какой backend отработал.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from llm_proxy_service.config import (
    STYLE_ANTHROPIC,
    STYLE_OPENAI,
    STYLE_OPENAI_RESPONSES,
    BackendConfig,
)

ANTHROPIC_VERSION = "2023-06-01"


class UpstreamError(Exception):
    """Backend недоступен или вернул некорректный ответ."""


async def call_backend(
    client: httpx.AsyncClient,
    backend: BackendConfig,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Выполнить запрос к backend и вернуть OpenAI-compatible JSON ответа."""
    if backend.style == STYLE_ANTHROPIC:
        return await _call_anthropic(client, backend, body)
    if backend.style == STYLE_OPENAI_RESPONSES:
        return await _call_openai_responses(client, backend, body)
    return await _call_openai(client, backend, body)


async def _call_openai(
    client: httpx.AsyncClient,
    backend: BackendConfig,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Проксировать запрос в OpenAI-compatible chat/completions."""
    url = backend.base_url.rstrip("/") + "/v1/chat/completions"
    payload = dict(body)
    payload["model"] = backend.model

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if backend.api_key:
        headers["Authorization"] = f"Bearer {backend.api_key}"

    try:
        response = await client.post(
            url, json=payload, headers=headers, timeout=backend.timeout_seconds
        )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"сетевая ошибка: {exc}") from exc

    if response.status_code >= 400:
        raise UpstreamError(
            f"HTTP {response.status_code}: {_short_body(response.text)}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamError("upstream вернул невалидный JSON") from exc

    _ensure_openai_content(data)
    return data


async def _call_openai_responses(
    client: httpx.AsyncClient,
    backend: BackendConfig,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Проксировать запрос в OpenAI Responses API (/v1/responses).

    Нужно для моделей (например gpt-5-codex), которые не поддерживаются
    endpoint-ом chat/completions. Ответ приводится к OpenAI chat-формату.
    """
    url = backend.base_url.rstrip("/") + "/v1/responses"
    payload = _openai_to_responses_payload(body, backend.model)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if backend.api_key:
        headers["Authorization"] = f"Bearer {backend.api_key}"

    try:
        response = await client.post(
            url, json=payload, headers=headers, timeout=backend.timeout_seconds
        )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"сетевая ошибка: {exc}") from exc

    if response.status_code >= 400:
        raise UpstreamError(
            f"HTTP {response.status_code}: {_short_body(response.text)}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamError("upstream вернул невалидный JSON") from exc

    text = _extract_responses_text(data)
    return build_openai_response(text, backend.model)


async def _call_anthropic(
    client: httpx.AsyncClient,
    backend: BackendConfig,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Проксировать запрос в Anthropic Messages API и вернуть OpenAI-формат."""
    url = backend.base_url.rstrip("/") + "/v1/messages"
    payload = _openai_to_anthropic_payload(body, backend.model)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if backend.api_key:
        headers["x-api-key"] = backend.api_key

    try:
        response = await client.post(
            url, json=payload, headers=headers, timeout=backend.timeout_seconds
        )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"сетевая ошибка: {exc}") from exc

    if response.status_code >= 400:
        raise UpstreamError(
            f"HTTP {response.status_code}: {_short_body(response.text)}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamError("upstream вернул невалидный JSON") from exc

    text = _extract_anthropic_text(data)
    return build_openai_response(text, backend.model)


def build_openai_response(text: str, model: str) -> dict[str, Any]:
    """Собрать OpenAI chat.completion-подобный объект из текста ответа."""
    return {
        "id": f"chatcmpl-proxy-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


def _ensure_openai_content(data: dict[str, Any]) -> None:
    """Проверить, что в ответе есть choices[0].message.content."""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise UpstreamError(
            "upstream вернул ответ без choices[0].message.content"
        ) from exc
    if not isinstance(content, str):
        raise UpstreamError("upstream вернул content не строкой")


def _openai_to_responses_payload(body: dict[str, Any], model: str) -> dict[str, Any]:
    """Преобразовать OpenAI chat-запрос в payload OpenAI Responses API."""
    messages = body.get("messages") or []
    input_items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        input_items.append(
            {"role": role, "content": _openai_content_to_responses(role, content)}
        )

    # temperature намеренно не отправляем: reasoning-модели (gpt-5-codex, o-серия)
    # отклоняют её с HTTP 400 "Unsupported parameter: 'temperature'".
    payload: dict[str, Any] = {
        "model": model,
        "input": input_items,
    }
    max_tokens = body.get("max_tokens")
    if max_tokens:
        payload["max_output_tokens"] = max_tokens
    return payload


def _openai_content_to_responses(role: Any, content: Any) -> Any:
    """Преобразовать content сообщения в формат Responses API (input_text/image)."""
    # Для assistant используется output_text, для остальных input_text.
    text_type = "output_text" if role == "assistant" else "input_text"

    if isinstance(content, str):
        return [{"type": text_type, "text": content}]
    if not isinstance(content, list):
        return [{"type": text_type, "text": str(content)}]

    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            parts.append({"type": text_type, "text": part.get("text", "")})
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url:
                parts.append({"type": "input_image", "image_url": url})
    return parts or [{"type": text_type, "text": ""}]


def _extract_responses_text(data: dict[str, Any]) -> str:
    """Достать текст из ответа Responses API (output_text или output[].content[])."""
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = data.get("output")
    if not isinstance(output, list):
        raise UpstreamError("Responses upstream вернул ответ без output")

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") in (
                "output_text",
                "text",
            ):
                parts.append(block.get("text", ""))

    text = "".join(parts).strip()
    if not text:
        raise UpstreamError("Responses upstream вернул пустой текст")
    return text


def _openai_to_anthropic_payload(body: dict[str, Any], model: str) -> dict[str, Any]:
    """Преобразовать OpenAI chat-запрос в Anthropic Messages payload."""
    messages = body.get("messages") or []
    system_parts: list[str] = []
    conversation: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            system_parts.append(_flatten_text(content))
            continue
        conversation.append(
            {"role": role, "content": _openai_content_to_anthropic(content)}
        )

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": body.get("max_tokens") or 4096,
        "temperature": body.get("temperature", 0.2),
        "messages": conversation,
    }
    if system_parts:
        system_prompt = "\n\n".join(part for part in system_parts if part)
        response_format = body.get("response_format")
        if isinstance(response_format, dict) and response_format.get("type") == (
            "json_object"
        ):
            system_prompt += (
                "\n\nВерни ответ строго как один JSON-объект без Markdown и пояснений."
            )
        payload["system"] = system_prompt
    return payload


def _openai_content_to_anthropic(content: Any) -> Any:
    """Преобразовать content сообщения OpenAI в Anthropic (текст + изображения)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif part_type == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            media_type, data = _parse_data_url(url)
            if data:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    }
                )
    return blocks or ""


def _parse_data_url(url: str) -> tuple[str, str]:
    """Разобрать data:<media>;base64,<data> в (media_type, base64_data)."""
    if not url.startswith("data:") or ";base64," not in url:
        return "image/png", ""
    header, _, data = url.partition(";base64,")
    media_type = header[len("data:") :] or "image/png"
    return media_type, data


def _flatten_text(content: Any) -> str:
    """Достать текст из content (строка или список частей)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    """Достать текст из content[].text Anthropic-ответа."""
    blocks = data.get("content")
    if not isinstance(blocks, list) or not blocks:
        raise UpstreamError("Anthropic upstream вернул пустой content")
    text = "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        raise UpstreamError("Anthropic upstream вернул content без текста")
    return text


def _short_body(text: str, limit: int = 500) -> str:
    """Обрезать тело ответа для диагностики."""
    return (text or "").strip()[:limit]
