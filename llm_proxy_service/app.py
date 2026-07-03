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
                    "has_api_key": bool(backend.api_key),
                }
                for backend in proxy_config.chain
            ],
        }

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

    for backend in proxy_config.chain:
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


app = create_app()
