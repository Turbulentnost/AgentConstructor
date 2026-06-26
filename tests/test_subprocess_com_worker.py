"""Тесты SubprocessComWorker без реального Outlook COM."""

import pytest

from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def make_task(
    tool_name: str,
    input_data: dict | None = None,
    timeout_seconds: int = 5,
) -> WorkerTask:
    """Создать WorkerTask для subprocess worker-тестов."""
    return WorkerTask(
        task_id=f"task-{tool_name}",
        tool_name=tool_name,
        input_data=input_data or {},
        timeout_seconds=timeout_seconds,
    )


def test_subprocess_com_worker_returns_worker_result() -> None:
    """SubprocessComWorker всегда возвращает WorkerResult."""
    result = SubprocessComWorker().execute(make_task("unknown.tool"))

    assert isinstance(result, WorkerResult)


def test_unknown_tool_returns_unknown_com_tool() -> None:
    """Неизвестный tool_name возвращает UNKNOWN_COM_TOOL."""
    result = SubprocessComWorker().execute(make_task("unknown.tool"))

    assert result.ok is False
    assert result.error_type == "UNKNOWN_COM_TOOL"


def test_email_send_returns_disabled_for_safety() -> None:
    """email.send безопасно заблокирован в subprocess worker."""
    result = SubprocessComWorker().execute(make_task("email.send"))

    assert result.ok is False
    assert result.error_type == "SEND_DISABLED_FOR_SAFETY"
    assert "Отправка писем" in (result.error_message or "")


def test_email_create_draft_returns_disabled_for_safety() -> None:
    """email.create_draft безопасно заблокирован в subprocess worker."""
    result = SubprocessComWorker().execute(make_task("email.create_draft"))

    assert result.ok is False
    assert result.error_type == "DRAFT_DISABLED_FOR_SAFETY"


def test_timeout_returns_worker_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зависший дочерний процесс завершается по timeout."""
    monkeypatch.setenv("ENABLE_TEST_WORKER_TOOLS", "1")

    result = SubprocessComWorker().execute(
        make_task(
            "test.sleep",
            input_data={"sleep_seconds": 5},
            timeout_seconds=1,
        )
    )

    assert result.ok is False
    assert result.error_type == "WORKER_TIMEOUT"
    assert "COM worker не ответил за 1 секунд" in (result.error_message or "")
    assert "[COM_DIAG] step=test_sleep seconds=5.0" in (result.error_message or "")


def test_test_sleep_is_disabled_without_env_flag() -> None:
    """test.sleep недоступен без ENABLE_TEST_WORKER_TOOLS=1."""
    result = SubprocessComWorker().execute(
        make_task(
            "test.sleep",
            input_data={"sleep_seconds": 0},
            timeout_seconds=2,
        )
    )

    assert result.ok is False
    assert result.error_type == "UNKNOWN_COM_TOOL"
