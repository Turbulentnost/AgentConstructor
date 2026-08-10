"""Тесты FastAPI-прокси: асинхронный fallback по цепочке backend-ов."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from llm_proxy_service import app as proxy_app  # noqa: E402
from llm_proxy_service.config import (  # noqa: E402
    STYLE_ANTHROPIC,
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


def test_models_endpoint_discovers_claude_models() -> None:
    """Claude-модели подтягиваются из Anthropic /v1/models для селекта."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[
            BackendConfig(
                name="claude",
                style=STYLE_ANTHROPIC,
                base_url="https://api.anthropic.com",
                model="claude-sonnet-4-6",
                api_key="sk-ant-test",
                timeout_seconds=5.0,
                display_name="Claude",
                supports_reasoning=True,
                discover_models=True,
            )
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/v1/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "claude-sonnet-4-6",
                        "display_name": "Claude Sonnet 4.6",
                    },
                    {
                        "id": "claude-opus-4-1",
                        "display_name": "Claude Opus 4.1",
                    },
                ]
            },
        )

    with TestClient(proxy_app.create_app(config)) as client:
        client.app.state.http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        try:
            response = client.get("/v1/models")
        finally:
            import asyncio

            asyncio.run(client.app.state.http_client.aclose())

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert ids == [
        "claude-sonnet-4-6",
        "claude-sonnet-4-6:internal",
        "claude-sonnet-4-6:reason",
        "claude-opus-4-1",
        "claude-opus-4-1:internal",
        "claude-opus-4-1:reason",
    ]


def test_models_endpoint_uses_configured_claude_models_without_discovery() -> None:
    """Если Claude discovery недоступен, показываем настроенные модели, не заглушку."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[
            BackendConfig(
                name="claude",
                style=STYLE_ANTHROPIC,
                base_url="https://api.anthropic.com",
                model="claude-sonnet-4-6",
                api_key=None,
                timeout_seconds=5.0,
                display_name="Claude",
                supports_reasoning=True,
                discover_models=True,
                configured_models=("claude-sonnet-4-6", "claude-opus-4-1"),
            )
        ],
    )

    with TestClient(proxy_app.create_app(config)) as client:
        response = client.get("/v1/models")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert "claude" not in ids
    assert ids == [
        "claude-sonnet-4-6",
        "claude-sonnet-4-6:internal",
        "claude-sonnet-4-6:reason",
        "claude-opus-4-1",
        "claude-opus-4-1:internal",
        "claude-opus-4-1:reason",
    ]


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


def test_claude_rate_limit_falls_back_to_next_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 на всех Claude-моделях — берём следующий backend (chatgpt)."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[
            _backend("chatgpt"),
            BackendConfig(
                name="claude",
                style=STYLE_ANTHROPIC,
                base_url="https://api.anthropic.com",
                model="claude-sonnet-4-6",
                api_key="sk-test",
                timeout_seconds=5.0,
                display_name="Claude",
                configured_models=(
                    "claude-sonnet-4-6",
                    "claude-opus-4-6",
                    "claude-sonnet-5",
                ),
            ),
            _backend("lmstudio"),
        ],
    )
    calls: list[str] = []

    async def fake_call_backend(client, backend, body):
        calls.append(f"{backend.name}:{backend.upstream_model}")
        if backend.name == "claude":
            raise UpstreamError("HTTP 429: Rate limit exceeded", status_code=429)
        if backend.name == "chatgpt":
            return build_openai_response("ok chatgpt", backend.model)
        raise UpstreamError("не должен вызываться")

    # Без реальных sleep на retry 429.
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(proxy_app, "call_backend", fake_call_backend)
    monkeypatch.setattr(proxy_app.asyncio, "sleep", no_sleep)

    payload = _payload()
    payload["model"] = "claude-sonnet-4-6"
    with TestClient(proxy_app.create_app(config)) as client:
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok chatgpt"
    assert calls[0].startswith("claude:")
    assert "chatgpt:chatgpt" in calls
    # Сначала перебираем Claude-модели, потом chatgpt.
    claude_models = [c.split(":", 1)[1] for c in calls if c.startswith("claude:")]
    assert "claude-sonnet-4-6" in claude_models
    assert "claude-opus-4-6" in claude_models
    assert "claude-sonnet-5" in claude_models


def test_claude_falls_back_sonnet_to_opus_to_sonnet5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка sonnet 4.6 → opus 4.6 → успех на sonnet 5."""
    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[
            BackendConfig(
                name="claude",
                style=STYLE_ANTHROPIC,
                base_url="https://api.anthropic.com",
                model="claude-sonnet-4-6",
                api_key="sk-test",
                timeout_seconds=5.0,
                display_name="Claude",
                configured_models=(
                    "claude-sonnet-4-6",
                    "claude-opus-4-6",
                    "claude-sonnet-5",
                ),
            ),
        ],
    )
    calls: list[str] = []

    async def fake_call_backend(client, backend, body):
        model = backend.upstream_model
        calls.append(model)
        if model == "claude-sonnet-4-6":
            raise UpstreamError("HTTP 502: Upstream unavailable", status_code=502)
        if model == "claude-opus-4-6":
            raise UpstreamError("HTTP 503: overloaded", status_code=503)
        if model == "claude-sonnet-5":
            return build_openai_response("ok sonnet5", model)
        raise UpstreamError(f"unexpected model {model}")

    monkeypatch.setattr(proxy_app, "call_backend", fake_call_backend)

    payload = _payload()
    payload["model"] = "claude-sonnet-4-6"
    with TestClient(proxy_app.create_app(config)) as client:
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok sonnet5"
    assert calls == [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-sonnet-5",
    ]


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


def test_selected_claude_model_routes_to_anthropic_messages() -> None:
    """Выбранная Claude-модель из селекта уходит в Anthropic messages payload."""
    import asyncio

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "ok"}]},
        )

    backend = BackendConfig(
        name="claude",
        style=STYLE_ANTHROPIC,
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-6",
        api_key="sk-ant-test",
        timeout_seconds=5.0,
        display_name="Claude",
        supports_reasoning=True,
    ).with_model("claude-opus-4-1").with_reasoning("reason")

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await call_backend(client, backend, _payload())

    result = asyncio.run(run())

    assert captured["url"].endswith("/v1/messages")
    assert captured["json"]["model"] == "claude-opus-4-1"
    assert "thinking" in captured["json"]
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

