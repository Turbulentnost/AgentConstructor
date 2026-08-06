"""Тесты API изображений агентов."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from llm_proxy_service.app import create_app
from llm_proxy_service.config import MinioConfig, ProxyConfig
from llm_proxy_service.minio_storage import StoredObject


@pytest.fixture
def media_client():
    storage = MagicMock()
    storage.put_agent_image.return_value = StoredObject(
        object_key="agents/test/avatar.png",
        content_type="image/png",
    )
    storage.get_agent_image.return_value = (b"\x89PNG\r\n", "image/png")

    app = create_app(
        ProxyConfig(
            host="127.0.0.1",
            port=8080,
            chain=[],
            minio=MinioConfig(
                endpoint="127.0.0.1:9000",
                access_key="minioadmin",
                secret_key="minioadmin",
                bucket="agent-constructor",
            ),
        )
    )
    app.state.agent_image_storage = storage
    return TestClient(app), storage


def test_upload_and_get_agent_image(media_client) -> None:
    client, storage = media_client
    files = {"file": ("avatar.png", b"fake-image-bytes", "image/png")}

    upload = client.post("/v1/agents/agent-123/image", files=files)
    assert upload.status_code == 200
    payload = upload.json()
    assert payload["image_url"].endswith("/v1/agents/agent-123/image")
    storage.put_agent_image.assert_called_once()

    fetched = client.get("/v1/agents/agent-123/image")
    assert fetched.status_code == 200
    assert fetched.content.startswith(b"\x89PNG")
