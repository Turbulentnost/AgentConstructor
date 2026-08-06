"""SQLAlchemy engine/session для Postgres пользователей."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from llm_proxy_service.models_user import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(database_url: str) -> Engine:
    """Создать engine, таблицы и глобальную session factory."""
    global _engine, _SessionLocal
    _engine = create_engine(database_url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_engine() -> Engine:
    """Вернуть инициализированный engine."""
    if _engine is None:
        raise RuntimeError("Database is not initialized")
    return _engine


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Контекстный менеджер сессии с commit/rollback."""
    if _SessionLocal is None:
        raise RuntimeError("Database is not initialized")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Создать новую сессию (вызывающий закрывает сам)."""
    if _SessionLocal is None:
        raise RuntimeError("Database is not initialized")
    return _SessionLocal()
