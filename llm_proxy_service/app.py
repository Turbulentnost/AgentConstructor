"""FastAPI-приложение LLM-прокси.

Endpoint ``POST /v1/chat/completions`` принимает OpenAI-compatible запрос и
последовательно (в порядке цепочки) пробует upstream-LLM. Возвращается первый
успешный ответ в OpenAI-формате. Обработка асинхронная: параллельные запросы
обслуживаются событийным циклом, а один общий httpx.AsyncClient переиспользует
соединения.

Также: auth пользователей (1С), синхронизация в Postgres, аватарки в MinIO.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from llm_proxy_service.agent_media import router as agent_media_router
from llm_proxy_service.auth_api import router as auth_router
from llm_proxy_service.config import ProxyConfig, load_proxy_config
from llm_proxy_service.db import init_db
from llm_proxy_service.minio_storage import AgentImageStorage, MinioStorageError
from llm_proxy_service.sync_users import (
    get_sync_status,
    run_scheduled_sync,
    sync_users_from_onec,
)
from llm_proxy_service.upstream import UpstreamError, call_backend

logger = logging.getLogger("llm_proxy")


def create_app(config: ProxyConfig | None = None) -> FastAPI:
    """Создать FastAPI-приложение прокси с заданной (или загруженной) конфигурацией."""
    proxy_config = config or load_proxy_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Создать общий httpx.AsyncClient на время жизни приложения."""
        app.state.agent_image_storage = None
        app.state.scheduler = None
        if proxy_config.auth is not None and proxy_config.auth.database_url:
            try:
                init_db(proxy_config.auth.database_url)
                logger.info("Postgres users DB ready")
            except Exception as exc:
                logger.warning("Postgres init failed: %s", exc)

        if proxy_config.minio is not None:
            try:
                app.state.agent_image_storage = AgentImageStorage(
                    endpoint=proxy_config.minio.endpoint,
                    access_key=proxy_config.minio.access_key,
                    secret_key=proxy_config.minio.secret_key,
                    bucket=proxy_config.minio.bucket,
                    secure=proxy_config.minio.secure,
                )
                logger.info(
                    "MinIO для аватаров: %s / %s",
                    proxy_config.minio.endpoint,
                    proxy_config.minio.bucket,
                )
            except MinioStorageError as exc:
                logger.warning("MinIO недоступен: %s", exc)

        if (
            proxy_config.auth is not None
            and proxy_config.onec is not None
            and proxy_config.auth.database_url
        ):
            if proxy_config.auth.sync_on_startup:
                try:
                    sync_users_from_onec(proxy_config.onec)
                except Exception as exc:
                    logger.warning("Startup 1C user sync failed: %s", exc)
            try:
                from apscheduler.schedulers.background import BackgroundScheduler
                from apscheduler.triggers.cron import CronTrigger

                scheduler = BackgroundScheduler()
                cron = (proxy_config.auth.sync_cron or "").strip()
                if cron:
                    # "мин час день месяц день_недели" — ежедневно без Celery/Redis.
                    parts = cron.split()
                    if len(parts) != 5:
                        raise ValueError(
                            f"USER_SYNC_CRON должен быть из 5 полей, получено: {cron!r}"
                        )
                    trigger = CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4],
                    )
                    scheduler.add_job(
                        run_scheduled_sync,
                        trigger=trigger,
                        args=[proxy_config.onec],
                        id="onec_user_sync",
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                    )
                    logger.info("Scheduled 1C user sync cron=%s", cron)
                else:
                    hours = max(proxy_config.auth.sync_interval_hours, 1.0)
                    scheduler.add_job(
                        run_scheduled_sync,
                        "interval",
                        hours=hours,
                        args=[proxy_config.onec],
                        id="onec_user_sync",
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                    )
                    logger.info("Scheduled 1C user sync every %s hours", hours)
                scheduler.start()
                app.state.scheduler = scheduler
            except Exception as exc:
                logger.warning("Scheduler not started: %s", exc)

        async with httpx.AsyncClient() as client:
            app.state.http_client = client
            yield

        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="AgentConstructor LLM Proxy", lifespan=lifespan)
    app.state.proxy_config = proxy_config
    app.include_router(agent_media_router)
    app.include_router(auth_router)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Вернуть статус и текущую цепочку backend-ов."""
        return {
            "status": "ok",
            "minio": proxy_config.minio is not None
            and getattr(app.state, "agent_image_storage", None) is not None,
            "auth_db": bool(proxy_config.auth and proxy_config.auth.database_url),
            "onec": bool(proxy_config.onec),
            "user_sync": get_sync_status(),
            "user_sync_cron": (
                proxy_config.auth.sync_cron if proxy_config.auth else None
            ),
            "chain": [
                {
                    "name": backend.name,
                    "style": backend.style,
                    "base_url": backend.base_url,
                    "model": backend.upstream_model,
                    "display_name": backend.display_name,
                    "supports_reasoning": backend.supports_reasoning,
                    "discover_models": backend.discover_models,
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
        client: httpx.AsyncClient = app.state.http_client
        for backend in proxy_config.chain:
            model_items = await _models_for_backend(client, backend)
            for item in model_items:
                model_id = item["id"]
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
                            "display_name": item.get("display_name") or backend.display_name,
                            "upstream_model": item.get("upstream_model") or backend.upstream_model,
                            "supports_reasoning": item.get(
                                "supports_reasoning", backend.supports_reasoning
                            ),
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
        if backend.name == "claude" and (
            model_id.startswith("claude-") or model_id.startswith("claude:")
        ):
            base_model, mode = _split_model_mode(requested_model.strip())
            selected = backend.with_model(base_model)
            return [selected.with_reasoning(mode)]
    return proxy_config.chain


async def _models_for_backend(
    client: httpx.AsyncClient,
    backend,
) -> list[dict[str, Any]]:
    """Вернуть selectable-модели backend-а, включая discovery для Claude."""
    if backend.name == "claude" and backend.discover_models:
        if not backend.api_key:
            return _configured_models_for_backend(backend)
        discovered = await _discover_anthropic_models(client, backend)
        if discovered:
            return discovered
        # Если Anthropic запретил /v1/models (403 Request not allowed), всё равно
        # показываем конкретные модели из конфигурации, а не общий пункт "Claude".
        return _configured_models_for_backend(backend)
    items: list[dict[str, Any]] = []
    for model_id in backend.model_ids():
        _, _, mode = model_id.partition(":")
        items.append(
            {
                "id": model_id,
                "display_name": backend.display_name,
                "upstream_model": backend.upstream_model,
                "supports_reasoning": backend.supports_reasoning,
                "reasoning_mode": mode or None,
            }
        )
    return items


def _configured_models_for_backend(backend) -> list[dict[str, Any]]:
    """Собрать selectable-модели из явной конфигурации backend-а."""
    items: list[dict[str, Any]] = []
    for model_id in backend.configured_model_ids():
        display_name = _display_name_for_model(backend, model_id)
        items.append(
            {
                "id": model_id,
                "display_name": display_name,
                "upstream_model": model_id,
                "supports_reasoning": backend.supports_reasoning,
                "reasoning_mode": None,
            }
        )
        if backend.supports_reasoning:
            for mode in ("internal", "reason"):
                items.append(
                    {
                        "id": f"{model_id}:{mode}",
                        "display_name": display_name,
                        "upstream_model": model_id,
                        "supports_reasoning": True,
                        "reasoning_mode": mode,
                    }
                )
    return items


def _display_name_for_model(backend, model_id: str) -> str:
    """Сделать человекочитаемую подпись для модели."""
    if backend.name != "claude":
        return backend.display_name
    text = model_id.removeprefix("claude-").replace("-", " ")
    return "Claude " + " ".join(part.capitalize() for part in text.split())


async def _discover_anthropic_models(
    client: httpx.AsyncClient,
    backend,
) -> list[dict[str, Any]]:
    """Получить список моделей Claude через Anthropic /v1/models."""
    url = backend.base_url.rstrip("/") + "/v1/models"
    headers = {
        "Accept": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": backend.api_key,
    }
    raw_models: list[dict[str, Any]] = []
    after_id: str | None = None
    for _ in range(20):
        params = {"after_id": after_id} if after_id else None
        try:
            response = await client.get(
                url,
                headers=headers,
                params=params,
                timeout=backend.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            logger.warning("Не удалось получить модели Claude: %s", exc)
            return []
        if response.status_code >= 400:
            logger.warning(
                "Claude /v1/models вернул HTTP %s: %s",
                response.status_code,
                response.text[:300],
            )
            return []
        try:
            payload = response.json()
        except ValueError:
            logger.warning("Claude /v1/models вернул невалидный JSON")
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        raw_models.extend(item for item in data if isinstance(item, dict))
        if not payload.get("has_more"):
            break
        next_after_id = payload.get("last_id")
        if not isinstance(next_after_id, str) or not next_after_id:
            break
        after_id = next_after_id

    items: list[dict[str, Any]] = []
    for raw in raw_models:
        model_id = str(raw.get("id") or "").strip()
        if not model_id:
            continue
        display_name = str(raw.get("display_name") or raw.get("name") or model_id)
        items.append(
            {
                "id": model_id,
                "display_name": display_name,
                "upstream_model": model_id,
                "supports_reasoning": backend.supports_reasoning,
                "reasoning_mode": None,
            }
        )
        if backend.supports_reasoning:
            for mode in ("internal", "reason"):
                items.append(
                    {
                        "id": f"{model_id}:{mode}",
                        "display_name": display_name,
                        "upstream_model": model_id,
                        "supports_reasoning": True,
                        "reasoning_mode": mode,
                    }
                )
    return items


def _split_model_mode(model_id: str) -> tuple[str, str | None]:
    """Разобрать id вида model:internal/model:reason."""
    base, sep, mode = model_id.partition(":")
    if sep and mode in {"internal", "reason"}:
        return base, mode
    return model_id, None


app = create_app()
