"""Тесты HumanApprovalRepository на tmp SQLite."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from agent_desktop_constructor.app.core.models.human_approval import (
    HumanApprovalRecord,
    HumanApprovalStatus,
)
from agent_desktop_constructor.storage.database import (
    create_engine_for_sqlite,
    create_session_factory,
    init_database,
)
from agent_desktop_constructor.storage.entities import HumanApprovalRequestEntity
from agent_desktop_constructor.storage.repositories import HumanApprovalRepository


def make_repository(tmp_path: Path) -> HumanApprovalRepository:
    """Создать repository на временной SQLite базе."""
    engine = create_engine_for_sqlite(tmp_path / "approvals.db")
    init_database(engine)
    return HumanApprovalRepository(create_session_factory(engine))


def make_record(
    approval_id: str = "approval-1",
    *,
    agent_id: str = "agent-1",
    run_id: str = "run-1",
) -> HumanApprovalRecord:
    """Создать pending-запись подтверждения."""
    return HumanApprovalRecord(
        approval_id=approval_id,
        run_id=run_id,
        agent_id=agent_id,
        node_id="review",
        question="Продолжить выполнение?",
        options=["Подтвердить", "Отклонить"],
        created_at=datetime.now(timezone.utc),
    )


def test_create_request_stores_record(tmp_path: Path) -> None:
    """create_request сохраняет запись."""
    repository = make_repository(tmp_path)

    repository.create_request(make_record())

    assert repository.get_request("approval-1").approval_id == "approval-1"


def test_get_request_returns_record(tmp_path: Path) -> None:
    """get_request возвращает запись."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())

    record = repository.get_request("approval-1")

    assert record.question == "Продолжить выполнение?"


def test_list_pending_returns_pending(tmp_path: Path) -> None:
    """list_pending возвращает pending записи."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())

    assert [record.approval_id for record in repository.list_pending()] == [
        "approval-1"
    ]


def test_list_pending_filters_by_agent_id(tmp_path: Path) -> None:
    """list_pending(agent_id) фильтрует по агенту."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record("approval-1", agent_id="agent-1"))
    repository.create_request(make_record("approval-2", agent_id="agent-2"))

    pending = repository.list_pending(agent_id="agent-2")

    assert [record.approval_id for record in pending] == ["approval-2"]


def test_answer_request_approved_updates_status(tmp_path: Path) -> None:
    """answer_request approved обновляет статус."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())

    record = repository.answer_request(
        "approval-1",
        HumanApprovalStatus.APPROVED,
        "Подтвердить",
    )

    assert record.status == HumanApprovalStatus.APPROVED
    assert record.selected_option == "Подтвердить"


def test_answer_request_rejected_updates_status(tmp_path: Path) -> None:
    """answer_request rejected обновляет статус."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())

    record = repository.answer_request(
        "approval-1",
        HumanApprovalStatus.REJECTED,
        "Отклонить",
        "Не нужно",
    )

    assert record.status == HumanApprovalStatus.REJECTED
    assert record.comment == "Не нужно"


def test_answered_at_is_filled(tmp_path: Path) -> None:
    """answered_at заполняется при ответе."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())

    record = repository.answer_request(
        "approval-1",
        HumanApprovalStatus.APPROVED,
        "Подтвердить",
    )

    assert record.answered_at is not None


def test_cannot_answer_approval_twice(tmp_path: Path) -> None:
    """Нельзя ответить на один approval дважды."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())
    repository.answer_request(
        "approval-1",
        HumanApprovalStatus.APPROVED,
        "Подтвердить",
    )

    with pytest.raises(ValueError, match="уже обработан"):
        repository.answer_request(
            "approval-1",
            HumanApprovalStatus.REJECTED,
            "Отклонить",
        )


def test_cancel_request_marks_cancelled(tmp_path: Path) -> None:
    """cancel_request переводит запрос в cancelled."""
    repository = make_repository(tmp_path)
    repository.create_request(make_record())

    record = repository.cancel_request("approval-1", "Запуск отменён")

    assert record.status == HumanApprovalStatus.CANCELLED
    assert record.comment == "Запуск отменён"


def test_options_json_preserves_russian_text(tmp_path: Path) -> None:
    """options_json сохраняет кириллицу без ASCII escaping."""
    engine = create_engine_for_sqlite(tmp_path / "approvals.db")
    init_database(engine)
    session_factory = create_session_factory(engine)
    repository = HumanApprovalRepository(session_factory)

    repository.create_request(make_record())

    with session_factory() as session:
        entity = session.scalars(select(HumanApprovalRequestEntity)).one()
        assert "Подтвердить" in entity.options_json

