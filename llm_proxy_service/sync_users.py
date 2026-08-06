"""Ежедневная синхронизация пользователей из 1С в Postgres.

Источник правды — SQL Server erp_pm (v8users). Локальный Postgres хранит
копию для экрана входа и проверки пароля без прямого обращения к 1С на каждый
запрос. Расписание — APScheduler внутри llm_proxy_service (Celery не нужен:
одна задача раз в сутки, без отдельного брокера).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete

from llm_proxy_service.config import OneCConfig
from llm_proxy_service.db import session_scope
from llm_proxy_service.models_user import UserEntity
from llm_proxy_service.onec.sql import OneCSqlConfig, export_users

logger = logging.getLogger("llm_proxy.sync_users")

_lock = threading.Lock()
_last_status: dict[str, Any] = {
    "ok": None,
    "started_at": None,
    "finished_at": None,
    "fetched": 0,
    "created": 0,
    "updated": 0,
    "removed_bootstrap": 0,
    "error": None,
    "notes": [],
}


@dataclass(frozen=True)
class SyncResult:
    """Итог синхронизации."""

    fetched: int
    created: int
    updated: int
    removed_bootstrap: int = 0
    notes: tuple[str, ...] = ()


def get_sync_status() -> dict[str, Any]:
    """Последний статус sync (для /health и диагностики)."""
    with _lock:
        return dict(_last_status)


def _to_sql_config(cfg: OneCConfig) -> OneCSqlConfig:
    return OneCSqlConfig(
        server=cfg.server,
        database=cfg.database,
        trusted=cfg.trusted,
        user=cfg.user,
        password=cfg.password,
        driver=cfg.driver,
        port=cfg.port,
    )


def _purge_bootstrap_rows(session) -> int:
    """Удалить временные BOOTSTRAP-* записи — они не из 1С."""
    result = session.execute(
        delete(UserEntity).where(UserEntity.onec_uid.like("BOOTSTRAP-%"))
    )
    return int(result.rowcount or 0)


def sync_users_from_onec(onec: OneCConfig) -> SyncResult:
    """Upsert пользователей из 1С; email/avatar пользователя не затираются."""
    started = datetime.now(timezone.utc)
    with _lock:
        _last_status.update(
            {
                "ok": None,
                "started_at": started.isoformat(),
                "finished_at": None,
                "error": None,
            }
        )

    try:
        export = export_users(_to_sql_config(onec), department_sql=onec.department_sql)
        created = 0
        updated = 0
        now = datetime.now(timezone.utc)

        with session_scope() as session:
            removed_bootstrap = _purge_bootstrap_rows(session)
            for row in export.users:
                if not row.user_id:
                    continue
                entity = session.get(UserEntity, row.user_id)
                if entity is None:
                    entity = UserEntity(
                        onec_uid=row.user_id,
                        login=row.login,
                        display_name=row.display_name or row.login,
                        department=row.department or "",
                        password_data=row.password_data or b"",
                        email=row.email or "",
                        synced_at=now,
                        notes="",
                    )
                    session.add(entity)
                    created += 1
                    continue

                entity.login = row.login
                entity.display_name = row.display_name or row.login
                entity.department = row.department or entity.department
                entity.password_data = row.password_data or entity.password_data
                # email / avatar_object_key сохраняем как есть
                if not entity.email and row.email:
                    entity.email = row.email
                entity.synced_at = now
                entity.updated_at = now
                if entity.notes.startswith("bootstrap_local_user"):
                    entity.notes = ""
                updated += 1

        result = SyncResult(
            fetched=len(export.users),
            created=created,
            updated=updated,
            removed_bootstrap=removed_bootstrap,
            notes=tuple(export.notes),
        )
        finished = datetime.now(timezone.utc)
        with _lock:
            _last_status.update(
                {
                    "ok": True,
                    "finished_at": finished.isoformat(),
                    "fetched": result.fetched,
                    "created": result.created,
                    "updated": result.updated,
                    "removed_bootstrap": result.removed_bootstrap,
                    "error": None,
                    "notes": list(result.notes),
                }
            )
        logger.info(
            "1C user sync done: fetched=%s created=%s updated=%s removed_bootstrap=%s notes=%s",
            result.fetched,
            result.created,
            result.updated,
            result.removed_bootstrap,
            result.notes,
        )
        return result
    except Exception as exc:
        finished = datetime.now(timezone.utc)
        with _lock:
            _last_status.update(
                {
                    "ok": False,
                    "finished_at": finished.isoformat(),
                    "error": str(exc),
                }
            )
        logger.exception("1C user sync failed")
        raise


def run_scheduled_sync(onec: OneCConfig) -> None:
    """Обёртка для APScheduler: ошибки логируются, процесс не падает."""
    try:
        sync_users_from_onec(onec)
    except Exception:
        # Уже залогировано в sync_users_from_onec
        return
