"""FastAPI-приложение LLM-прокси.

Endpoint ``POST /v1/chat/completions`` принимает OpenAI-compatible запрос и
последовательно (в порядке цепочки) пробует upstream-LLM. Возвращается первый
успешный ответ в OpenAI-формате. Обработка асинхронная: параллельные запросы
обслуживаются событийным циклом, а один общий httpx.AsyncClient переиспользует
соединения.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from llm_proxy_service.config import ProxyConfig, load_proxy_config
from llm_proxy_service.upstream import UpstreamError, call_backend

logger = logging.getLogger("llm_proxy")


def create_app(config: ProxyConfig | None = None) -> FastAPI:
    """Создать FastAPI-приложение прокси с заданной (или загруженной) конфигурацией."""
    proxy_config = config or load_proxy_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Создать общий httpx.AsyncClient на время жизни приложения."""
        async with httpx.AsyncClient() as client:
            app.state.http_client = client
            yield

    app = FastAPI(title="AgentConstructor LLM Proxy", lifespan=lifespan)
    app.state.proxy_config = proxy_config

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Вернуть статус и текущую цепочку backend-ов."""
        return {
            "status": "ok",
            "chain": [
                {
                    "name": backend.name,
                    "style": backend.style,
                    "base_url": backend.base_url,
                    "model": backend.model,
                    "display_name": backend.display_name,
                    "supports_reasoning": backend.supports_reasoning,
                    "has_api_key": bool(backend.api_key),
                }
                for backend in proxy_config.chain
            ],
        }

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        """Вернуть список selectable-моделей для OpenAI-compatible клиентов."""
        data: list[dict[str, Any]] = []
        seen: set[str] = set()
        for backend in proxy_config.chain:
            for model_id in backend.model_ids():
                if model_id in seen:
                    continue
                seen.add(model_id)
                _, _, reasoning_mode = model_id.partition(":")
                data.append(
                    {
                        "id": model_id,
                        "object": "model",
                        "created": 0,
                        "owned_by": backend.name,
                        "metadata": {
                            "display_name": backend.display_name,
                            "upstream_model": backend.model,
                            "supports_reasoning": backend.supports_reasoning,
                            "reasoning_mode": reasoning_mode or None,
                        },
                    }
                )
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        """Проксировать chat-completions запрос по цепочке fallback."""
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Тело запроса не является JSON"}},
            )
        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Тело запроса должно быть JSON-объектом"}},
            )

        return await _dispatch(app, proxy_config, body)

    return app


async def _dispatch(
    app: FastAPI, proxy_config: ProxyConfig, body: dict[str, Any]
) -> JSONResponse:
    """Последовательно пробовать backend-ы и вернуть первый успешный ответ."""
    if not proxy_config.chain:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "Не настроен ни один upstream-LLM"}},
        )

    client: httpx.AsyncClient = app.state.http_client
    errors: list[str] = []

    chain = _chain_for_requested_model(proxy_config, body.get("model"))
    for backend in chain:
        try:
            data = await call_backend(client, backend, body)
        except UpstreamError as exc:
            logger.warning("Backend %s недоступен: %s", backend.name, exc)
            errors.append(f"{backend.name}: {exc}")
            continue
        logger.info("Ответ получен от backend %s", backend.name)
        return JSONResponse(status_code=200, content=data)

    message = "Все upstream-LLM недоступны. " + "; ".join(errors)
    logger.error(message)
    return JSONResponse(status_code=502, content={"error": {"message": message}})


def _chain_for_requested_model(
    proxy_config: ProxyConfig,
    requested_model: object,
) -> list:
    """Выбрать backend по model из запроса или вернуть fallback-цепочку.

    Если клиент выбрал модель из `/v1/models`, запрос идёт только в этот backend.
    Если модель неизвестна (например, старый клиент шлёт upstream model_name),
    сохраняем прежнее поведение — пробуем всю fallback-цепочку.
    """
    if not isinstance(requested_model, str) or not requested_model.strip():
        return proxy_config.chain
    model_id = requested_model.strip().casefold()
    for backend in proxy_config.chain:
        base_id = backend.name.casefold()
        if model_id == base_id:
            return [backend]
        for mode in ("internal", "reason"):
            if model_id == f"{base_id}:{mode}":
                return [backend.with_reasoning(mode)]
    return proxy_config.chain


app = create_app()
