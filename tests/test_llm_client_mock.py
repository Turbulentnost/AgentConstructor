"""Mock-тесты OpenAI-compatible LLM client без реального HTTP."""

from __future__ import annotations

import json
import threading
from io import BytesIO
from urllib.error import HTTPError
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


def test_client_serializes_parallel_complete_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Параллельные complete() на одном client не отправляют HTTP одновременно."""
    active = 0
    max_active = 0
    calls = 0
    lock = threading.Lock()
    first_inside = threading.Event()
    release_first = threading.Event()

    def fake_urlopen(http_request, timeout):
        nonlocal active, max_active, calls
        with lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
            call_no = calls
        if call_no == 1:
            first_inside.set()
            assert release_first.wait(timeout=3)
        with lock:
            active -= 1
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    client = OpenAICompatibleLLMClient(LLMConfig())
    errors: list[BaseException] = []

    def run_complete() -> None:
        try:
            client.complete(make_request())
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    first = threading.Thread(target=run_complete)
    second = threading.Thread(target=run_complete)
    first.start()
    assert first_inside.wait(timeout=3)
    second.start()
    release_first.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert calls == 2
    assert max_active == 1


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


def test_client_sends_max_tokens_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент отправляет max_tokens из конфига, чтобы ответ не обрывался."""
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

    OpenAICompatibleLLMClient(LLMConfig(max_tokens=8192)).complete(make_request())

    assert captured["payload"]["max_tokens"] == 8192


def test_client_strips_markdown_fences_from_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Клиент снимает ```json обёртку, если модель вернула JSON в code block."""

    def fake_urlopen(http_request, timeout):
        return FakeHTTPResponse(
            {
                "choices": [
                    {"message": {"content": "```json\n{\"ok\": true}\n```"}}
                ]
            }
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    response = OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())

    assert response.content == "{\"ok\": true}"


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


def test_client_retries_without_response_format_on_http_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если endpoint не поддерживает response_format, клиент повторяет запрос без него."""
    payloads: list[dict] = []

    def fake_urlopen(http_request, timeout):
        payload = json.loads(http_request.data.decode("utf-8"))
        payloads.append(payload)
        if len(payloads) == 1:
            raise HTTPError(
                http_request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=BytesIO(b"response_format is not supported"),
            )
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    response = OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())

    assert response.content == "{\"ok\": true}"
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]


def test_http_error_includes_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP error включает тело ответа для диагностики model/endpoint ошибок."""

    def fake_urlopen(http_request, timeout):
        raise HTTPError(
            http_request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":"model not found"}'),
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(LLMResponseError, match="model not found"):
        OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())


def test_client_passes_cancel_callback_to_http_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_cancel_callback пробрасывается в read_with_retry."""
    captured: dict = {}

    def fake_read_with_retry(urlopen_callable, http_request, timeout, **kwargs):
        captured["cancel_callback"] = kwargs.get("cancel_callback")
        return json.dumps(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        ).encode("utf-8")

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.read_with_retry",
        fake_read_with_retry,
    )

    client = OpenAICompatibleLLMClient(LLMConfig())
    cb = lambda: False
    client.set_cancel_callback(cb)
    client.complete(make_request())

    assert captured["cancel_callback"] is cb


def test_client_propagates_cancelled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMCancelledError из HTTP-слоя не маскируется как connection error."""
    from agent_desktop_constructor.app.llm.errors import LLMCancelledError

    def fake_read_with_retry(*args, **kwargs):
        raise LLMCancelledError("stop")

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.read_with_retry",
        fake_read_with_retry,
    )

    with pytest.raises(LLMCancelledError):
        OpenAICompatibleLLMClient(LLMConfig()).complete(make_request())

