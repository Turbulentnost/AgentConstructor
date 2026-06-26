"""Тесты модели AgentRunEvent."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.app.core.models.run_events import (
    AgentRunEvent,
    AgentRunEventType,
)


def make_event(**overrides) -> AgentRunEvent:
    """Создать валидное событие выполнения."""
    payload = {
        "event_id": "event-1",
        "run_id": "run-1",
        "event_type": AgentRunEventType.RUN_STARTED,
        "message": "Запуск агента начат",
        "created_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return AgentRunEvent.model_validate(payload)


def test_agent_run_event_can_be_created() -> None:
    """AgentRunEvent создаётся с обязательными полями."""
    event = make_event()

    assert event.event_id == "event-1"
    assert event.event_type == AgentRunEventType.RUN_STARTED


@pytest.mark.parametrize("field_name", ["event_id", "run_id", "message"])
def test_required_text_fields_cannot_be_empty(field_name: str) -> None:
    """event_id, run_id и message не могут быть пустыми."""
    with pytest.raises(ValidationError):
        make_event(**{field_name: "   "})


def test_details_uses_default_factory() -> None:
    """details создаётся как независимый dict по умолчанию."""
    first = make_event(event_id="event-1")
    second = make_event(event_id="event-2")

    first.details["ключ"] = "значение"

    assert second.details == {}


def test_agent_run_event_serializes_and_restores_with_pydantic() -> None:
    """AgentRunEvent сериализуется и восстанавливается через Pydantic."""
    event = make_event(details={"сообщение": "готово"})

    restored = AgentRunEvent.model_validate(event.model_dump(mode="json"))

    assert restored == event

