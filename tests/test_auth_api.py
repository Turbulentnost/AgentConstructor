"""Тесты auth API llm_proxy_service (без реального 1С/Postgres)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_proxy_service.app import create_app
from llm_proxy_service.config import AuthConfig, BackendConfig, ProxyConfig
from llm_proxy_service.db import init_db
from llm_proxy_service.models_user import Base, UserEntity
from llm_proxy_service.onec.password import sha1_base64


def _encode_data(structure: str, key: bytes = b"\x11\x22\x33\x44") -> bytes:
    key_size = len(key)
    payload = structure.encode("utf-8")
    out = bytearray(1 + key_size + len(payload))
    out[0] = key_size
    out[1 : 1 + key_size] = key
    for index, value in enumerate(payload):
        out[1 + key_size + index] = value ^ key[index % key_size]
    return bytes(out)


@pytest.fixture()
def auth_app(tmp_path, monkeypatch):
    password = "secret-pass"
    plain = sha1_base64(password)
    upper = sha1_base64(password.upper())
    data = _encode_data(f'{{"id",1,"{plain},{upper}"}}')

    db_url = f"sqlite+pysqlite:///{tmp_path / 'auth.db'}"
    init_db(db_url)
    from llm_proxy_service import db as db_mod

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    db_mod._engine = engine
    db_mod._SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    session = db_mod._SessionLocal()
    session.add(
        UserEntity(
            onec_uid="AABBCC",
            login="testuser",
            display_name="Тест Пользователь",
            department="ИТ",
            password_data=data,
            email="",
            synced_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    session.close()

    config = ProxyConfig(
        host="127.0.0.1",
        port=8080,
        chain=[
            BackendConfig(
                name="dummy",
                style="openai",
                base_url="http://127.0.0.1:9",
                model="x",
                api_key=None,
                timeout_seconds=1,
                display_name="dummy",
            )
        ],
        minio=None,
        onec=None,
        auth=AuthConfig(
            jwt_secret="test-secret",
            jwt_ttl_hours=1,
            admin_token="admin-token",
            sync_interval_hours=24,
            sync_on_startup=False,
            database_url=db_url,
        ),
    )
    app = create_app(config)
    return app, password


def test_list_users_directory(auth_app) -> None:
    app, _password = auth_app
    client = TestClient(app)
    all_users = client.get("/v1/auth/users")
    assert all_users.status_code == 200
    payload = all_users.json()
    assert payload["total"] == 1
    assert payload["users"][0]["login"] == "testuser"
    assert "password" not in payload["users"][0]
    assert "password_data" not in payload["users"][0]

    filtered = client.get("/v1/auth/users", params={"q": "тест"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1

    empty = client.get("/v1/auth/users", params={"q": "неттакого"})
    assert empty.status_code == 200
    assert empty.json()["total"] == 0


def test_login_and_me(auth_app) -> None:
    app, password = auth_app
    client = TestClient(app)
    bad = client.post("/v1/auth/login", json={"login": "testuser", "password": "nope"})
    assert bad.status_code == 401

    ok = client.post("/v1/auth/login", json={"login": "testuser", "password": password})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    assert ok.json()["user"]["display_name"] == "Тест Пользователь"

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["department"] == "ИТ"


def test_patch_rejects_fio(auth_app) -> None:
    app, password = auth_app
    client = TestClient(app)
    token = client.post(
        "/v1/auth/login", json={"login": "testuser", "password": password}
    ).json()["access_token"]
    resp = client.patch(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "Хакер"},
    )
    assert resp.status_code == 422

    email_resp = client.patch(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "user@example.com"},
    )
    assert email_resp.status_code == 200
    assert email_resp.json()["email"] == "user@example.com"


def test_circular_avatar_bytes() -> None:
    from io import BytesIO

    from PIL import Image

    from llm_proxy_service.avatar_processing import make_circular_avatar

    img = Image.new("RGB", (120, 80), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    out = make_circular_avatar(buf.getvalue(), size=64)
    round_img = Image.open(BytesIO(out)).convert("RGBA")
    assert round_img.size == (64, 64)
    # Corner should be transparent after circular mask.
    assert round_img.getpixel((0, 0))[3] == 0
