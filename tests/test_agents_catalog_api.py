"""Интеграционные тесты каталога агентов / pins / run summaries."""

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
def catalog_app(tmp_path):
    password = "secret-pass"
    plain = sha1_base64(password)
    upper = sha1_base64(password.upper())
    data = _encode_data(f'{{"id",1,"{plain},{upper}"}}')

    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
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
    db_mod._SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    session = db_mod._SessionLocal()
    now = datetime.now(timezone.utc)
    session.add_all(
        [
            UserEntity(
                onec_uid="OWNER1",
                login="owner",
                display_name="Владелец",
                department="ИТ",
                password_data=data,
                synced_at=now,
            ),
            UserEntity(
                onec_uid="OTHER1",
                login="other",
                display_name="Другой",
                department="Бухгалтерия",
                password_data=data,
                synced_at=now,
            ),
            UserEntity(
                onec_uid="SAME1",
                login="same",
                display_name="Коллега",
                department="ИТ",
                password_data=data,
                synced_at=now,
            ),
        ]
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
    return create_app(config), password


def _token(client: TestClient, login: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"login": login, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_publish_acl_and_pins(catalog_app) -> None:
    app, password = catalog_app
    client = TestClient(app)
    owner = _token(client, "owner", password)
    other = _token(client, "other", password)
    same = _token(client, "same", password)

    deps = client.get("/v1/departments", headers=_auth(owner))
    assert deps.status_code == 200
    assert "ИТ" in deps.json()["departments"]

    published = client.post(
        "/v1/agents/catalog",
        headers=_auth(owner),
        json={
            "agent_id": "agent_demo",
            "name": "Демо агент",
            "description": "desc",
            "short_description": "short",
            "agent_spec": {"agent_id": "agent_demo", "name": "Демо агент"},
            "visibility": "department",
            "departments": [],
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["agent"]["pinned"] is True

    owner_list = client.get("/v1/agents/catalog", headers=_auth(owner))
    assert owner_list.status_code == 200
    assert owner_list.json()["count"] == 1

    same_list = client.get("/v1/agents/catalog", headers=_auth(same))
    assert same_list.json()["count"] == 1

    other_list = client.get("/v1/agents/catalog", headers=_auth(other))
    assert other_list.json()["count"] == 0

    # Открыть для всех
    patch = client.patch(
        "/v1/agents/catalog/agent_demo/access",
        headers=_auth(owner),
        json={"visibility": "all", "departments": []},
    )
    assert patch.status_code == 200
    assert client.get("/v1/agents/catalog", headers=_auth(other)).json()["count"] == 1

    # Other pin
    pins = client.put(
        "/v1/agents/pins",
        headers=_auth(other),
        json={"agent_ids": ["agent_demo"]},
    )
    assert pins.status_code == 200
    my_pins = client.get("/v1/agents/pins", headers=_auth(other))
    assert my_pins.json()["agent_ids"] == ["agent_demo"]

    detail = client.get("/v1/agents/catalog/agent_demo", headers=_auth(other))
    assert detail.status_code == 200
    assert detail.json()["agent"]["agent_spec"]["agent_id"] == "agent_demo"


def test_selected_departments_and_run_summary(catalog_app) -> None:
    app, password = catalog_app
    client = TestClient(app)
    owner = _token(client, "owner", password)
    other = _token(client, "other", password)

    resp = client.post(
        "/v1/agents/catalog",
        headers=_auth(owner),
        json={
            "agent_id": "agent_sel",
            "name": "Selected",
            "description": "",
            "agent_spec": {"agent_id": "agent_sel", "name": "Selected"},
            "visibility": "selected",
            "departments": ["Бухгалтерия"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/v1/agents/catalog", headers=_auth(other)).json()["count"] == 1

    summary = client.post(
        "/v1/agents/runs/summary",
        headers=_auth(other),
        json={
            "run_id": "run-1",
            "agent_id": "agent_sel",
            "status": "completed",
            "title": "Selected",
            "message": "ok",
        },
    )
    assert summary.status_code == 200, summary.text
    mine = client.get("/v1/agents/runs/mine", headers=_auth(other))
    assert mine.status_code == 200
    assert mine.json()["count"] == 1
    assert mine.json()["runs"][0]["run_id"] == "run-1"

    owner_mine = client.get("/v1/agents/runs/mine", headers=_auth(owner))
    assert owner_mine.json()["count"] == 0
