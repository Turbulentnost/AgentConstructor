"""Клиент загрузки изображений агента через LLM-прокси (MinIO)."""

from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from urllib import error, request


class AgentImageUploadError(RuntimeError):
    """Ошибка загрузки изображения агента."""


def upload_agent_image(
    proxy_base_url: str,
    agent_id: str,
    file_path: str,
    *,
    timeout_seconds: float = 60.0,
) -> str:
    """Загрузить файл изображения и вернуть публичный ``image_url``."""
    base = (proxy_base_url or "").strip().rstrip("/")
    if not base:
        raise AgentImageUploadError("Не задан URL LLM-прокси (llm_proxy_url)")
    safe_id = (agent_id or "").strip()
    if not safe_id:
        raise AgentImageUploadError("agent_id не задан")

    path = Path(file_path)
    if not path.is_file():
        raise AgentImageUploadError(f"Файл не найден: {file_path}")

    content = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    boundary = uuid.uuid4().hex
    body = _encode_multipart(boundary, "file", path.name, content, content_type)
    url = f"{base}/v1/agents/{safe_id}/image"
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AgentImageUploadError(
            f"Сервер вернул HTTP {exc.code}: {detail[:300]}"
        ) from exc
    except error.URLError as exc:
        raise AgentImageUploadError(f"Не удалось связаться с прокси: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise AgentImageUploadError("Прокси вернул невалидный JSON") from exc

    image_url = payload.get("image_url")
    if not isinstance(image_url, str) or not image_url.strip():
        raise AgentImageUploadError("В ответе прокси нет image_url")
    return image_url.strip()


def fetch_image_bytes(image_url: str, *, timeout_seconds: float = 20.0) -> bytes:
    """Скачать изображение по URL."""
    url = (image_url or "").strip()
    if not url:
        raise AgentImageUploadError("Пустой image_url")
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return response.read()
    except error.URLError as exc:
        raise AgentImageUploadError(f"Не удалось загрузить изображение: {exc.reason}") from exc


def _encode_multipart(
    boundary: str,
    field_name: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> bytes:
    parts: list[bytes] = [
        f"--{boundary}".encode(),
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"'
        ).encode(),
        f"Content-Type: {content_type}".encode(),
        b"",
        content,
        f"--{boundary}--".encode(),
        b"",
    ]
    return b"\r\n".join(parts)
