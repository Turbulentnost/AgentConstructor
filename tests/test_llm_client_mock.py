"""Mock-тесты OpenAI-compatible LLM client без реального HTTP."""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.errors import (
    LLMConnectionError,
    LLMResponseError,
)
from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.core.models.llm_config import LLMConfig


class FakeHTTPResponse:
    """Минимальный context manager для urllib response."""

    def __init__(self, payload: dict | bytes) -> None:
        """Сохранить payload ответа."""
        self._payload = payload

    def __enter__(self) -> FakeHTTPResponse:
        """Вернуть response."""
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        """Закрытие fake response не требуется."""
        return None

    def read(self) -> bytes:
        """Вернуть bytes payload."""
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


def make_request() -> LLMRequest:
    """Создать тестовый LLMRequest."""
    return LLMRequest(
        messages=[LLMMessage(role="user", content="Проверь Outlook")],
        temperature=0.2,
        model_name="openai/gpt-oss-120b",
        response_format="json_object",
    )


def test_client_calls_chat_completions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент формирует запрос к /v1/chat/completions."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    client = OpenAICompatibleLLMClient(LLMConfig())
    client.complete(make_request())

    assert captured["url"].endswith("/v1/chat/completions")


def test_client_uses_base_url_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент использует base_url из LLMConfig."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    config = LLMConfig(base_url="http://localhost:1234")
    OpenAICompatibleLLMClient(config).complete(make_request())

    assert captured["url"] == "http://localhost:1234/v1/chat/completions"


def test_client_uses_model_name_from_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент отправляет model_name openai/gpt-oss-120b."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["payload"] = json.loads(http_request.data.decode("utf-8"))
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())

    assert captured["payload"]["model"] == "openai/gpt-oss-120b"


def test_client_uses_timeout_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout берётся из LLMConfig."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["timeout"] = timeout
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    OpenAICompatibleLLMClient(LLMConfig(timeout_seconds=7)).complete(make_request())

    assert captured["timeout"] == 7


def test_connection_error_becomes_llm_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка соединения превращается в LLMConnectionError."""

    def fake_urlopen(http_request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(LLMConnectionError):
        OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())


def test_invalid_payload_becomes_llm_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Невалидный ответ превращается в LLMResponseError."""

    def fake_urlopen(http_request, timeout):
        return FakeHTTPResponse({"unexpected": []})

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(LLMResponseError):
        OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())


def test_client_does_not_make_real_http_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit-тест не делает реальный HTTP-запрос."""
    called = {"urlopen": False}

    def fake_urlopen(http_request, timeout):
        called["urlopen"] = True
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    response = OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())

    assert called["urlopen"] is True
    assert response.content == "{\"ok\": true}"

