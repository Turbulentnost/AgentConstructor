"""HTTP API загрузки и выдачи изображений агентов."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from llm_proxy_service.minio_storage import AgentImageStorage, MinioStorageError

logger = logging.getLogger("llm_proxy.agent_media")

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

router = APIRouter(tags=["agent-media"])


def _validate_agent_id(agent_id: str) -> str:
    cleaned = (agent_id or "").strip()
    if not cleaned or not _AGENT_ID_RE.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail="Некорректный agent_id")
    return cleaned


def _storage(request: Request) -> AgentImageStorage:
    storage = getattr(request.app.state, "agent_image_storage", None)
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail="MinIO не настроен для хранения изображений агентов",
        )
    return storage


def _public_image_url(request: Request, agent_id: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/v1/agents/{agent_id}/image"


@router.post("/v1/agents/{agent_id}/image")
async def upload_agent_image(
    agent_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Загрузить изображение агента в MinIO."""
    safe_id = _validate_agent_id(agent_id)
    storage = _storage(request)
    payload = await file.read()
    filename = file.filename or "avatar.png"
    content_type = file.content_type

    try:
        storage.put_agent_image(
            safe_id,
            payload,
            filename=filename,
            content_type=content_type,
        )
    except MinioStorageError as exc:
        logger.exception("Ошибка загрузки изображения агента %s", safe_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "agent_id": safe_id,
        "image_url": _public_image_url(request, safe_id),
        "filename": filename,
    }


@router.get("/v1/agents/{agent_id}/image")
async def get_agent_image(agent_id: str, request: Request) -> Response:
    """Вернуть изображение агента из MinIO."""
    safe_id = _validate_agent_id(agent_id)
    storage = _storage(request)
    try:
        result = storage.get_agent_image(safe_id)
    except MinioStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Изображение агента не найдено")
    payload, content_type = result
    return Response(content=payload, media_type=content_type)
