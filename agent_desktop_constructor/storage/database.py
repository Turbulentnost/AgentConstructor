"""Настройка локальной SQLite-базы для хранения агентов и запусков."""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DEFAULT_DB_PATH = Path("./data/agents.db")


class Base(DeclarativeBase):
    """Базовый класс SQLAlchemy entities проекта."""


def create_engine_for_sqlite(db_path: Path | str = DEFAULT_DB_PATH) -> Engine:
    """Создать SQLAlchemy engine для SQLite и подготовить директорию базы."""
    if str(db_path) == ":memory:":
        return create_engine("sqlite:///:memory:", future=True)

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{path.resolve().as_posix()}"
    return create_engine(database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Создать фабрику сессий без глобальной сессии."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database(engine: Engine) -> None:
    """Создать таблицы storage-слоя."""
    import agent_desktop_constructor.storage.entities  # noqa: F401

    Base.metadata.create_all(engine)
