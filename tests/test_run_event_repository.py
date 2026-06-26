"""Тесты RunEventRepository на tmp SQLite."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from agent_desktop_constructor.app.core.models.run_events import (
    AgentRunEvent,
    AgentRunEventType,
)
from agent_desktop_constructor.storage.database import (
    create_engine_for_sqlite,
    create_session_factory,
    init_database,
)
from agent_desktop_constructor.storage.entities import AgentRunEventEntity
from agent_desktop_constructor.storage.repositories import RunEventRepository


def make_repository(tmp_path: Path) -> RunEventRepository:
    """Создать repository на временной SQLite базе."""
    engine = create_engine_for_sqlite(tmp_path / "events.db")
    init_database(engine)
    return RunEventRepository(create_session_factory(engine))


def make_event(
    event_id: str,
    run_id: str = "run-1",
    event_type: AgentRunEventType = AgentRunEventType.RUN_STARTED,
    *,
    created_at: datetime | None = None,
    details: dict | None = None,
) -> AgentRunEvent:
    """Создать событие для repository-тестов."""
    return AgentRunEvent(
        event_id=event_id,
        run_id=run_id,
        event_type=event_type,
        message=f"Событие {event_id}",
        details=details or {},
        created_at=created_at or datetime.now(timezone.utc),
    )


def test_add_event_stores_event(tmp_path: Path) -> None:
    """add_event сохраняет событие."""
    repository = make_repository(tmp_path)

    repository.add_event(make_event("event-1"))

    assert len(repository.list_events("run-1")) == 1


def test_list_events_returns_event(tmp_path: Path) -> None:
    """list_events возвращает сохранённое событие."""
    repository = make_repository(tmp_path)
    event = make_event("event-1", details={"узел": "validate"})

    repository.add_event(event)

    assert repository.list_events("run-1")[0].details == {"узел": "validate"}


def test_list_events_unknown_run_returns_empty_list(tmp_path: Path) -> None:
    """list_events для неизвестного run_id возвращает пустой список."""
    repository = make_repository(tmp_path)

    assert repository.list_events("unknown-run") == []


def test_list_recent_events_returns_latest_events(tmp_path: Path) -> None:
    """list_recent_events возвращает последние события."""
    repository = make_repository(tmp_path)
    start = datetime.now(timezone.utc)
    repository.add_event(make_event("event-1", created_at=start))
    repository.add_event(make_event("event-2", created_at=start + timedelta(seconds=1)))
    repository.add_event(make_event("event-3", created_at=start + timedelta(seconds=2)))

    recent = repository.list_recent_events(limit=2)

    assert [event.event_id for event in recent] == ["event-3", "event-2"]


def test_details_json_preserves_russian_text(tmp_path: Path) -> None:
    """details_json сохраняет русский текст без ASCII escaping."""
    engine = create_engine_for_sqlite(tmp_path / "events.db")
    init_database(engine)
    session_factory = create_session_factory(engine)
    repository = RunEventRepository(session_factory)

    repository.add_event(make_event("event-1", details={"сообщение": "узел выполнен"}))

    with session_factory() as session:
        entity = session.scalars(select(AgentRunEventEntity)).one()
        assert "узел выполнен" in entity.details_json


def test_delete_events_for_run_deletes_only_selected_run(tmp_path: Path) -> None:
    """delete_events_for_run удаляет события конкретного запуска."""
    repository = make_repository(tmp_path)
    repository.add_event(make_event("event-1", run_id="run-1"))
    repository.add_event(make_event("event-2", run_id="run-2"))

    repository.delete_events_for_run("run-1")

    assert repository.list_events("run-1") == []
    assert [event.event_id for event in repository.list_events("run-2")] == ["event-2"]

