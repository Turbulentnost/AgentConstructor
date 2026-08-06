"""Хранение изображений агентов в MinIO."""

from __future__ import annotations

import io
import logging
import mimetypes
from dataclasses import dataclass

logger = logging.getLogger("llm_proxy.minio")

_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class StoredObject:
    """Метаданные загруженного объекта."""

    object_key: str
    content_type: str


class MinioStorageError(RuntimeError):
    """Ошибка работы с MinIO."""


class AgentImageStorage:
    """Загрузка и чтение аватаров агентов из MinIO."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise MinioStorageError(
                "Пакет minio не установлен. Выполните: pip install minio"
            ) from exc

        self._bucket = bucket
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            logger.info("Создан bucket MinIO: %s", self._bucket)

    @staticmethod
    def _object_key(agent_id: str, filename: str) -> str:
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            ext = ".png"
        safe_id = "".join(ch for ch in agent_id if ch.isalnum() or ch in "-_")
        return f"agents/{safe_id or 'unknown'}/avatar{ext}"

    def put_agent_image(
        self,
        agent_id: str,
        data: bytes,
        *,
        filename: str,
        content_type: str | None = None,
    ) -> StoredObject:
        """Сохранить изображение агента и вернуть ключ объекта."""
        if not data:
            raise MinioStorageError("Пустой файл изображения")
        object_key = self._object_key(agent_id, filename)
        guessed = content_type or mimetypes.guess_type(filename)[0] or "image/png"
        stream = io.BytesIO(data)
        self._client.put_object(
            self._bucket,
            object_key,
            stream,
            length=len(data),
            content_type=guessed,
        )
        return StoredObject(object_key=object_key, content_type=guessed)

    def get_agent_image(self, agent_id: str) -> tuple[bytes, str] | None:
        """Прочитать изображение агента; None если объект не найден."""
        prefix = f"agents/{''.join(ch for ch in agent_id if ch.isalnum() or ch in '-_')}/avatar"
        for ext in _ALLOWED_EXTENSIONS:
            key = prefix + ext
            found = self.get_object(key)
            if found is not None:
                return found
        return None

    @staticmethod
    def _safe_id(value: str) -> str:
        return "".join(ch for ch in value if ch.isalnum() or ch in "-_") or "unknown"

    def put_user_avatar(self, onec_uid: str, data: bytes) -> StoredObject:
        """Сохранить круглую аватарку пользователя как PNG."""
        if not data:
            raise MinioStorageError("Пустой файл изображения")
        object_key = f"users/{self._safe_id(onec_uid)}/avatar.png"
        stream = io.BytesIO(data)
        self._client.put_object(
            self._bucket,
            object_key,
            stream,
            length=len(data),
            content_type="image/png",
        )
        return StoredObject(object_key=object_key, content_type="image/png")

    def get_object(self, object_key: str) -> tuple[bytes, str] | None:
        """Прочитать объект по ключу."""
        if not object_key:
            return None
        try:
            response = self._client.get_object(self._bucket, object_key)
        except Exception:
            return None
        try:
            payload = response.read()
            content_type = response.headers.get("content-type", "application/octet-stream")
            return payload, content_type
        finally:
            response.close()
            response.release_conn()

    def get_user_avatar(self, onec_uid: str, object_key: str = "") -> tuple[bytes, str] | None:
        """Прочитать аватарку пользователя."""
        key = object_key or f"users/{self._safe_id(onec_uid)}/avatar.png"
        return self.get_object(key)
