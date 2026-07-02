"""Mock-тесты Anthropic (Claude) LLM client без реального HTTP."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from agent_desktop_constructor.app.llm.anthropic_client import AnthropicLLMClient
from agent_desktop_constructor.app.llm.errors import (
    LLMConnectionError,
    LLMResponseError,
)
from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.core.models.llm_config import LLMConfig


class FakeHTTPResponse:
    """Минимальный context manager для urllib response."""

    def __init__(self, payload: dict | bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


def make_config() -> LLMConfig:
    """Создать конфиг Claude."""
    return LLMConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model_name="claude-3-5-sonnet-latest",
        api_key="sk-ant-test",
    )


def make_request() -> LLMRequest:
    """Создать тестовый LLMRequest c system и user сообщениями."""
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content="Ты планировщик."),
            LLMMessage(role="user", content="Составь план по Outlook"),
        ],
        temperature=0.2,
        model_name="claude-3-5-sonnet-latest",
        response_format="json_object",
    )


def _text_response(text: str) -> dict:
    """Собрать Anthropic-ответ с одним text-блоком."""
    return {"content": [{"type": "text", "text": text}]}


def test_client_calls_messages_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент обращается к /v1/messages."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        return FakeHTTPResponse(_text_response('{"ok": true}'))

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    AnthropicLLMClient(make_config()).complete(make_request())

    assert captured["url"] == "https://api.anthropic.com/v1/messages"


def test_client_sets_anthropic_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент отправляет x-api-key и anthropic-version."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["headers"] = http_request.headers
        return FakeHTTPResponse(_text_response('{"ok": true}'))

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    AnthropicLLMClient(make_config()).complete(make_request())

    assert captured["headers"]["X-api-key"] == "sk-ant-test"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"


def test_client_separates_system_from_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System-сообщение уходит в поле system, а не в messages."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["payload"] = json.loads(http_request.data.decode("utf-8"))
        return FakeHTTPResponse(_text_response('{"ok": true}'))

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    AnthropicLLMClient(make_config()).complete(make_request())

    payload = captured["payload"]
    assert "Ты планировщик." in payload["system"]
    assert payload["messages"] == [
        {"role": "user", "content": "Составь план по Outlook"}
    ]
    assert payload["max_tokens"] == 4096


def test_client_extracts_text_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент достаёт текст из content[].text."""

    def fake_urlopen(http_request, timeout):
        return FakeHTTPResponse(_text_response('{"agent_name": "test"}'))

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    response = AnthropicLLMClient(make_config()).complete(make_request())

    assert response.content == '{"agent_name": "test"}'


def test_client_strips_markdown_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент убирает ```json обёртку из ответа."""

    def fake_urlopen(http_request, timeout):
        return FakeHTTPResponse(
            _text_response('```json\n{"agent_name": "test"}\n```')
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    response = AnthropicLLMClient(make_config()).complete(make_request())

    assert response.content == '{"agent_name": "test"}'


def test_connection_error_becomes_llm_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка соединения превращается в LLMConnectionError."""

    def fake_urlopen(http_request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(LLMConnectionError):
        AnthropicLLMClient(make_config()).complete(make_request())


def test_http_error_includes_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP-ошибка включает тело ответа для диагностики."""

    def fake_urlopen(http_request, timeout):
        raise HTTPError(
            http_request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid api key"}'),
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(LLMResponseError, match="invalid api key"):
        AnthropicLLMClient(make_config()).complete(make_request())
