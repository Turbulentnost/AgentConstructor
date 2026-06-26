"""Тесты безопасного OutlookComWorker без реального Outlook."""

import pytest

from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask
from agent_desktop_constructor.workers.outlook_com_errors import ComUnavailableError
from agent_desktop_constructor.workers.outlook_com_worker import OutlookComWorker
from agent_desktop_constructor.workers import outlook_com_worker


def make_task(tool_name: str, input_data: dict | None = None) -> WorkerTask:
    """Создать WorkerTask для Outlook worker-тестов."""
    return WorkerTask(
        task_id=f"task-{tool_name}",
        tool_name=tool_name,
        input_data=input_data or {},
    )


def test_outlook_com_worker_can_be_created() -> None:
    """OutlookComWorker создаётся в safe_mode."""
    worker = OutlookComWorker()

    assert worker.safe_mode is True


def test_email_send_returns_disabled_result() -> None:
    """email.send возвращает SEND_DISABLED_FOR_SAFETY."""
    result = OutlookComWorker().execute(make_task("email.send"))

    assert result.ok is False
    assert result.error_type == "SEND_DISABLED_FOR_SAFETY"


def test_email_create_draft_returns_disabled_result() -> None:
    """email.create_draft возвращает DRAFT_DISABLED_FOR_SAFETY."""
    result = OutlookComWorker().execute(make_task("email.create_draft"))

    assert result.ok is False
    assert result.error_type == "DRAFT_DISABLED_FOR_SAFETY"


def test_unknown_tool_name_returns_unknown_com_tool() -> None:
    """Неизвестный tool_name возвращает UNKNOWN_COM_TOOL."""
    result = OutlookComWorker().execute(make_task("word.extract_text"))

    assert result.ok is False
    assert result.error_type == "UNKNOWN_COM_TOOL"


def test_unsupported_outlook_tool_returns_not_implemented() -> None:
    """Неподдержанный outlook tool возвращает OUTLOOK_TOOL_NOT_IMPLEMENTED."""
    result = OutlookComWorker().execute(make_task("outlook.delete_mail"))

    assert result.ok is False
    assert result.error_type == "OUTLOOK_TOOL_NOT_IMPLEMENTED"


def test_search_mail_com_unavailable_returns_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """outlook.search_mail при недоступном COM не выбрасывает исключение наружу."""

    def raise_com_unavailable(input_data: dict) -> dict:
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(outlook_com_worker, "search_mail", raise_com_unavailable)

    result = OutlookComWorker(allow_direct_com_calls=True).execute(
        make_task("outlook.search_mail")
    )

    assert isinstance(result, WorkerResult)
    assert result.ok is False
    assert result.error_type == "COM_NOT_AVAILABLE"


def test_read_calendar_com_unavailable_returns_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """outlook.read_calendar при недоступном COM не выбрасывает исключение наружу."""

    def raise_com_unavailable(input_data: dict) -> dict:
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(outlook_com_worker, "read_calendar", raise_com_unavailable)

    result = OutlookComWorker(allow_direct_com_calls=True).execute(
        make_task("outlook.read_calendar")
    )

    assert isinstance(result, WorkerResult)
    assert result.ok is False
    assert result.error_type == "COM_NOT_AVAILABLE"


def test_direct_search_mail_is_disabled_outside_subprocess() -> None:
    """Прямой read-route не выполняет COM без разрешения subprocess."""
    result = OutlookComWorker().execute(make_task("outlook.search_mail"))

    assert result.ok is False
    assert result.error_type == "DIRECT_COM_CALL_DISABLED"


def test_worker_always_returns_worker_result_for_common_errors() -> None:
    """Worker возвращает WorkerResult для обычных safe-mode ошибок."""
    worker = OutlookComWorker()
    results = [
        worker.execute(make_task("email.send")),
        worker.execute(make_task("email.create_draft")),
        worker.execute(make_task("outlook.move_mail")),
        worker.execute(make_task("unknown.tool")),
    ]

    assert all(isinstance(result, WorkerResult) for result in results)


def test_worker_does_not_send_mail_when_safe_mode_false() -> None:
    """Даже safe_mode=False не включает реальную отправку писем."""
    result = OutlookComWorker(safe_mode=False).execute(make_task("email.send"))

    assert result.ok is False
    assert result.error_type == "SEND_DISABLED_FOR_SAFETY"


def test_worker_does_not_create_drafts_when_safe_mode_false() -> None:
    """Даже safe_mode=False не включает создание черновиков."""
    result = OutlookComWorker(safe_mode=False).execute(make_task("email.create_draft"))

    assert result.ok is False
    assert result.error_type == "DRAFT_DISABLED_FOR_SAFETY"
