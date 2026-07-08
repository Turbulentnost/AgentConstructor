"""Тесты FastAPI-прокси: асинхронный fallback по цепочке backend-ов."""

from __future__ import annotations

import json

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
        display_name=name,
    )


def _make_client(monkeypatch: pytest.MonkeyPatch, behaviour: dict[str, object]):
    """Создать TestClient прокси с подменённым call_backend."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[_backend("chatgpt"), _backend("lmstudio")],
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
    """Если ChatGPT доступен, ответ приходит от него без обращения к остальным."""
    client = _make_client(
        monkeypatch,
        {
            "chatgpt": "ответ chatgpt",
            "lmstudio": UpstreamError("не должно вызываться"),
        },
    )

    with client:
        response = client.post("/v1/chat/completions", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "ответ chatgpt"
    assert body["model"] == "chatgpt"


def test_falls_back_to_lmstudio_when_openai_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ChatGPT недоступен -> ответ берётся из LM Studio."""
    client = _make_client(
        monkeypatch,
        {
            "chatgpt": UpstreamError("chatgpt timeout"),
            "lmstudio": "локальный ответ",
        },
    )

    with client:
        response = client.post("/v1/chat/completions", json=_payload())

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "локальный ответ"


def test_models_endpoint_returns_selectable_models() -> None:
    """Селект в OpenAI-compatible чате получает актуальные модели прокси."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[
            BackendConfig(
                name="chatgpt",
                style="openai",
                base_url="https://api.openai.com",
                model="gpt-5.5",
                api_key="sk-test",
                timeout_seconds=5.0,
                display_name="Chat-GPT 5.5",
                supports_reasoning=True,
            ),
            _backend("lmstudio"),
        ],
    )

    with TestClient(proxy_app.create_app(config)) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert ids == ["chatgpt", "chatgpt:internal", "chatgpt:reason", "lmstudio"]


def test_selected_model_routes_to_that_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если в чате выбрали модель, прокси использует именно её backend."""
    client = _make_client(
        monkeypatch,
        {
            "chatgpt": "ответ chatgpt",
            "lmstudio": UpstreamError("не должен вызываться"),
        },
    )
    payload = _payload()
    payload["model"] = "chatgpt"

    with client:
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ответ chatgpt"


def test_returns_502_when_all_backends_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если все backend-ы упали, возвращается 502 с агрегированной ошибкой."""
    client = _make_client(
        monkeypatch,
        {
            "chatgpt": UpstreamError("chatgpt down"),
            "lmstudio": UpstreamError("lmstudio down"),
        },
    )

    with client:
        response = client.post("/v1/chat/completions", json=_payload())

    assert response.status_code == 502
    message = response.json()["error"]["message"]
    assert "chatgpt down" in message
    assert "lmstudio down" in message


def test_responses_style_calls_v1_responses_and_parses_output() -> None:
    """responses-стиль обращается к /v1/responses и приводит ответ к OpenAI-формату."""
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
                        "content": [{"type": "output_text", "text": "ответ responses"}],
                    }
                ]
            },
        )

    backend = BackendConfig(
        name="openai_reasoning",
        style=STYLE_OPENAI_RESPONSES,
        base_url="https://api.openai.com",
        model="gpt-5.5",
        api_key="sk-test",
        timeout_seconds=5.0,
        display_name="GPT 5.5",
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
    assert result["choices"][0]["message"]["content"] == "ответ responses"


def test_openai_reasoning_variant_adds_reasoning_payload() -> None:
    """Выбранный режим :reason уходит в OpenAI-compatible payload."""
    import asyncio

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json = request.read().decode("utf-8")
        assert '"reasoning":{"mode":"reason"}' in json.replace(" ", "")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}}
                ]
            },
        )

    backend = BackendConfig(
        name="chatgpt",
        style="openai",
        base_url="https://api.openai.com",
        model="gpt-5.5",
        api_key="sk-test",
        timeout_seconds=5.0,
        display_name="GPT 5.5",
        supports_reasoning=True,
    ).with_reasoning("reason")

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await call_backend(client, backend, _payload())

    result = asyncio.run(run())

    assert result["choices"][0]["message"]["content"] == "ok"


def test_lmstudio_json_object_response_format_converts_to_json_schema() -> None:
    """LM Studio не принимает json_object, поэтому прокси шлёт json_schema."""
    import asyncio

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "{\"ok\": true}"}}
                ]
            },
        )

    backend = BackendConfig(
        name="lmstudio",
        style="openai",
        base_url="http://127.0.0.1:1234",
        model="openai/gpt-oss-120b",
        api_key=None,
        timeout_seconds=5.0,
        display_name="LM Studio (gpt-oss-120b)",
    )

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await call_backend(
                client,
                backend,
                {
                    "messages": [{"role": "user", "content": "верни json"}],
                    "response_format": {"type": "json_object"},
                },
            )

    result = asyncio.run(run())

    response_format = captured["payload"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == {"type": "object"}
    assert result["choices"][0]["message"]["content"] == "{\"ok\": true}"

