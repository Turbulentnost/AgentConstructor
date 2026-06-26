"""Тесты модели HumanApprovalRecord."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.app.core.models.human_approval import (
    HumanApprovalRecord,
    HumanApprovalStatus,
)


def make_record(**overrides) -> HumanApprovalRecord:
    """Создать валидную запись подтверждения."""
    payload = {
        "approval_id": "approval-1",
        "run_id": "run-1",
        "agent_id": "agent-1",
        "node_id": "review",
        "question": "Продолжить?",
        "options": ["Подтвердить", "Отклонить"],
        "created_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return HumanApprovalRecord.model_validate(payload)


def test_human_approval_record_can_be_created() -> None:
    """HumanApprovalRecord создаётся."""
    record = make_record()

    assert record.approval_id == "approval-1"
    assert record.status == HumanApprovalStatus.PENDING


@pytest.mark.parametrize("field_name", ["approval_id", "run_id", "question"])
def test_required_text_fields_cannot_be_empty(field_name: str) -> None:
    """Обязательные текстовые поля не могут быть пустыми."""
    with pytest.raises(ValidationError):
        make_record(**{field_name: "   "})


def test_empty_options_are_rejected() -> None:
    """Пустой список options вызывает ошибку."""
    with pytest.raises(ValidationError):
        make_record(options=[])


def test_default_status_is_pending() -> None:
    """status по умолчанию pending."""
    assert make_record().status == HumanApprovalStatus.PENDING


def test_answered_status_requires_answered_at() -> None:
    """approved/rejected требуют answered_at."""
    with pytest.raises(ValidationError):
        make_record(status=HumanApprovalStatus.APPROVED)

