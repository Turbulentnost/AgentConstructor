"""Тесты FastAPI-прокси: асинхронный fallback по цепочке backend-ов."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from llm_proxy_service import app as proxy_app  # noqa: E402
from llm_proxy_service.config import (  # noqa: E402
    STYLE_OPENAI_RESPONSES,
    BackendConfig,
    ProxyConfig,
)
from llm_proxy_service.upstream import (  # noqa: E402
    UpstreamError,
    build_openai_response,
    call_backend,
)


def _backend(name: str) -> BackendConfig:
    """Собрать простой backend для теста."""
    return BackendConfig(
        name=name,
        style="openai",
        base_url=f"http://{name}.local",
        model=name,
        api_key=None,
        timeout_seconds=5.0,
    )


def _make_client(monkeypatch: pytest.MonkeyPatch, behaviour: dict[str, object]):
    """Создать TestClient прокси с подменённым call_backend."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[_backend("codex"), _backend("chatgpt"), _backend("lmstudio")],
    )

    async def fake_call_backend(client, backend, body):
        outcome = behaviour[backend.name]
        if isinstance(outcome, Exception):
            raise outcome
        return build_openai_response(str(outcome), backend.model)

    monkeypatch.setattr(proxy_app, "call_backend", fake_call_backend)
    return TestClient(proxy_app.create_app(config))


def _payload() -> dict:
    """Минимальный OpenAI chat-completions запрос."""
    return {
        "model": "ignored",
        "messages": [{"role": "user", "content": "привет"}],
    }


def test_uses_first_backend_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если Codex доступен, ответ приходит от него без обращения к остальным."""
    client = _make_client(
        monkeypatch,
        {
            "codex": "ответ codex",
            "chatgpt": UpstreamError("не должно вызываться"),
            "lmstudio": UpstreamError("не должно вызываться"),
        },
    )

    with client:
        response = client.post("/v1/chat/completions", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "ответ codex"
    assert body["model"] == "codex"


def test_falls_back_to_lmstudio_when_openai_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex и ChatGPT недоступны -> ответ берётся из LM Studio."""
    client = _make_client(
        monkeypatch,
        {
            "codex": UpstreamError("codex 500"),
            "chatgpt": UpstreamError("chatgpt timeout"),
            "lmstudio": "локальный ответ",
        },
    )

    with client:
        response = client.post("/v1/chat/completions", json=_payload())

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "локальный ответ"


def test_returns_502_when_all_backends_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если все backend-ы упали, возвращается 502 с агрегированной ошибкой."""
    client = _make_client(
        monkeypatch,
        {
            "codex": UpstreamError("codex down"),
            "chatgpt": UpstreamError("chatgpt down"),
            "lmstudio": UpstreamError("lmstudio down"),
        },
    )

    with client:
        response = client.post("/v1/chat/completions", json=_payload())

    assert response.status_code == 502
    message = response.json()["error"]["message"]
    assert "codex down" in message
    assert "lmstudio down" in message


def test_responses_style_calls_v1_responses_and_parses_output() -> None:
    """codex-стиль обращается к /v1/responses и приводит ответ к OpenAI-формату."""
    import asyncio

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "ответ codex"}],
                    }
                ]
            },
        )

    backend = BackendConfig(
        name="codex",
        style=STYLE_OPENAI_RESPONSES,
        base_url="https://api.openai.com",
        model="gpt-5-codex",
        api_key="sk-test",
        timeout_seconds=5.0,
    )

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await call_backend(
                client,
                backend,
                {"messages": [{"role": "user", "content": "привет"}]},
            )

    result = asyncio.run(run())

    assert captured["url"].endswith("/v1/responses")
    assert result["choices"][0]["message"]["content"] == "ответ codex"
