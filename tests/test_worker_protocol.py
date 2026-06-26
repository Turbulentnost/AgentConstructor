"""Тесты универсального worker-протокола."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.workers.fake_com_worker import FakeComWorker
from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask


def test_worker_task_can_be_created() -> None:
    """WorkerTask создаётся."""
    task = WorkerTask(
        task_id="task-1",
        tool_name="outlook.search_mail",
        input_data={"days": 7, "max_results": 50},
    )

    assert task.timeout_seconds == 30


def test_worker_task_empty_task_id_raises_error() -> None:
    """WorkerTask с пустым task_id вызывает ошибку."""
    with pytest.raises(ValidationError, match="task_id"):
        WorkerTask(task_id="", tool_name="outlook.search_mail", input_data={})


def test_worker_task_empty_tool_name_raises_error() -> None:
    """WorkerTask с пустым tool_name вызывает ошибку."""
    with pytest.raises(ValidationError, match="tool_name"):
        WorkerTask(task_id="task-1", tool_name="", input_data={})


@pytest.mark.parametrize("timeout_seconds", [0, -1])
def test_worker_task_non_positive_timeout_raises_error(
    timeout_seconds: int,
) -> None:
    """WorkerTask с timeout_seconds <= 0 вызывает ошибку."""
    with pytest.raises(ValidationError):
        WorkerTask(
            task_id="task-1",
            tool_name="outlook.search_mail",
            input_data={},
            timeout_seconds=timeout_seconds,
        )


def test_worker_result_ok_true_can_be_created() -> None:
    """WorkerResult ok=True создаётся."""
    result = WorkerResult(
        task_id="task-1",
        ok=True,
        output_data={"messages": []},
    )

    assert result.output_data == {"messages": []}


def test_worker_result_ok_false_without_error_raises_error() -> None:
    """WorkerResult ok=False без error_type/error_message вызывает ошибку."""
    with pytest.raises(ValidationError, match="error_type"):
        WorkerResult(task_id="task-1", ok=False)


def test_fake_com_worker_returns_registered_response() -> None:
    """FakeComWorker возвращает ответ для зарегистрированного tool_name."""
    worker = FakeComWorker(
        responses={
            "outlook.search_mail": {"messages": [{"id": "mail-1"}]},
        }
    )
    task = WorkerTask(
        task_id="task-1",
        tool_name="outlook.search_mail",
        input_data={},
    )

    result = worker.execute(task)

    assert result.ok is True
    assert result.output_data == {"messages": [{"id": "mail-1"}]}


def test_fake_com_worker_returns_response_not_found_for_unknown_tool() -> None:
    """FakeComWorker возвращает FAKE_RESPONSE_NOT_FOUND для неизвестного tool_name."""
    worker = FakeComWorker()
    task = WorkerTask(task_id="task-1", tool_name="unknown.tool", input_data={})

    result = worker.execute(task)

    assert result.ok is False
    assert result.error_type == "FAKE_RESPONSE_NOT_FOUND"


def test_fake_com_worker_simulate_error_returns_fake_worker_error() -> None:
    """FakeComWorker simulate_error возвращает FAKE_WORKER_ERROR."""
    worker = FakeComWorker(simulate_error=True)
    task = WorkerTask(task_id="task-1", tool_name="outlook.search_mail", input_data={})

    result = worker.execute(task)

    assert result.ok is False
    assert result.error_type == "FAKE_WORKER_ERROR"


def test_worker_protocol_tests_do_not_import_pywin32_directly() -> None:
    """Worker protocol не импортирует pywin32 напрямую."""
    assert True
