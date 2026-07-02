"""Тесты фабрики LLM-клиентов и Bearer-авторизации OpenAI-клиента."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.client_factory import build_llm_client
from agent_desktop_constructor.app.llm.fallback_client import FallbackLLMClient
from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.core.models.llm_config import LLMConfig


class FakeHTTPResponse:
    """Минимальный context manager для urllib response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_factory_returns_anthropic_client_for_anthropic_provider() -> None:
    """provider=anthropic даёт клиент с fallback на LM Studio."""
    client = build_llm_client(LLMConfig(provider="anthropic"))
    assert isinstance(client, FallbackLLMClient)
    assert client.config.provider == "anthropic"
    assert client.fallback_config.base_url == "http://192.168.1.157:1234"


def test_factory_returns_openai_client_for_default_provider() -> None:
    """provider по умолчанию даёт OpenAICompatibleLLMClient."""
    client = build_llm_client(LLMConfig())
    assert isinstance(client, OpenAICompatibleLLMClient)


def test_openai_client_sends_bearer_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI-клиент добавляет Authorization: Bearer при наличии api_key."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["headers"] = http_request.headers
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    config = LLMConfig(
        provider="openai_compatible",
        base_url="https://api.openai.com",
        model_name="gpt-4o-mini",
        api_key="sk-openai-test",
    )
    OpenAICompatibleLLMClient(config).complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="привет")],
            model_name="gpt-4o-mini",
        )
    )

    assert captured["headers"]["Authorization"] == "Bearer sk-openai-test"


def test_openai_client_omits_authorization_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без api_key клиент не добавляет Authorization (для LM Studio)."""
    captured: dict = {}

    def fake_urlopen(http_request, timeout):
        captured["headers"] = http_request.headers
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.client.request.urlopen",
        fake_urlopen,
    )

    OpenAICompatibleLLMClient(LLMConfig()).complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="привет")],
            model_name="openai/gpt-oss-120b",
        )
    )

    assert "Authorization" not in captured["headers"]


def test_anthropic_factory_falls_back_to_lm_studio_on_http_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если Claude/Sonnet вернул 403, запрос повторяется через LM Studio."""
    calls: list[tuple[str, dict]] = []

    def fake_urlopen(http_request, timeout):
        payload = json.loads(http_request.data.decode("utf-8"))
        if http_request.full_url.endswith("/v1/messages"):
            calls.append(("anthropic", payload))
            raise HTTPError(
                http_request.full_url,
                403,
                "Forbidden",
                hdrs=None,
                fp=BytesIO(
                    b'{"error":{"type":"forbidden","message":"Request not allowed"}}'
                ),
            )
        calls.append(("lm_studio", payload))
        return FakeHTTPResponse(
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
        )

    monkeypatch.setattr(
        "agent_desktop_constructor.app.llm.anthropic_client.request.urlopen",
        fake_urlopen,
    )

    client = build_llm_client(
        LLMConfig(provider="anthropic", model_name="claude-sonnet-4-6")
    )
    response = client.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="Собери план")],
            model_name=client.config.model_name,
        )
    )

    assert response.content == "{\"ok\": true}"
    assert calls[0][0] == "anthropic"
    assert calls[0][1]["model"] == "claude-sonnet-4-6"
    assert calls[1][0] == "lm_studio"
    assert calls[1][1]["model"] == "openai/gpt-oss-120b"
