"""Тест sync upsert: email пользователя не затирается."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_proxy_service import db as db_mod
from llm_proxy_service.models_user import Base, UserEntity
from llm_proxy_service.onec.sql import OneCExportResult, OneCUserRow
from llm_proxy_service.sync_users import sync_users_from_onec


def test_sync_preserves_user_email(monkeypatch, tmp_path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'sync.db'}"
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
            onec_uid="UID1",
            login="ivan",
            display_name="Иван",
            department="Старое",
            password_data=b"\x01\x00",
            email="ivan@corp.local",
            avatar_object_key="users/UID1/avatar.png",
            synced_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    session.close()

    def fake_export(cfg, *, department_sql: str = ""):
        return OneCExportResult(
            users=[
                OneCUserRow(
                    user_id="UID1",
                    login="ivan",
                    display_name="Иван Иванов",
                    os_name="",
                    password_data=b"\x01\x02",
                    email="",
                    department="Новое",
                ),
                OneCUserRow(
                    user_id="UID2",
                    login="petr",
                    display_name="Пётр",
                    os_name="",
                    password_data=b"\x03\x04",
                    department="Склад",
                ),
            ],
            notes=["ok"],
        )

    monkeypatch.setattr("llm_proxy_service.sync_users.export_users", fake_export)

    class DummyOneC:
        server = "x"
        database = "y"
        trusted = True
        user = ""
        password = ""
        driver = "ODBC Driver 18 for SQL Server"
        port = None
        department_sql = ""

    # Временный хардкод-пользователь должен удаляться при sync из 1С.
    session = db_mod._SessionLocal()
    session.add(
        UserEntity(
            onec_uid="BOOTSTRAP-fake",
            login="fake",
            display_name="Fake",
            password_data=b"\x00",
            notes="bootstrap_local_user",
        )
    )
    session.commit()
    session.close()

    result = sync_users_from_onec(DummyOneC())  # type: ignore[arg-type]
    assert result.created == 1
    assert result.updated == 1
    assert result.removed_bootstrap == 1

    session = db_mod._SessionLocal()
    u1 = session.get(UserEntity, "UID1")
    u2 = session.get(UserEntity, "UID2")
    assert u1 is not None
    assert u1.email == "ivan@corp.local"
    assert u1.avatar_object_key == "users/UID1/avatar.png"
    assert u1.display_name == "Иван Иванов"
    assert u1.department == "Новое"
    assert u2 is not None
    assert u2.login == "petr"
    assert session.get(UserEntity, "BOOTSTRAP-fake") is None
    session.close()
