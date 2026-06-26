"""Тесты безопасного com_worker_process без реального Outlook."""

import subprocess
import sys

from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask


def run_process(
    input_text: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Запустить com_worker_process как дочерний Python-модуль."""
    return subprocess.run(
        [sys.executable, "-m", "agent_desktop_constructor.workers.com_worker_process"],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )


def make_task(tool_name: str) -> WorkerTask:
    """Создать WorkerTask для process-тестов."""
    return WorkerTask(
        task_id=f"task-{tool_name}",
        tool_name=tool_name,
        input_data={},
    )


def test_com_worker_process_returns_valid_json() -> None:
    """com_worker_process возвращает валидный WorkerResult JSON."""
    completed = run_process(make_task("unknown.tool").model_dump_json())

    result = WorkerResult.model_validate_json(completed.stdout)

    assert completed.returncode == 0
    assert result.error_type == "UNKNOWN_COM_TOOL"


def test_stdout_contains_only_json_for_unknown_tool() -> None:
    """stdout содержит только JSON, без диагностических строк."""
    completed = run_process(make_task("unknown.tool").model_dump_json())

    assert completed.stdout.strip().startswith("{")
    assert "[COM_DIAG]" not in completed.stdout
    WorkerResult.model_validate_json(completed.stdout)


def test_progress_goes_to_stderr_and_stdout_stays_json(monkeypatch) -> None:
    """COM_DIAG пишется в stderr, stdout остаётся чистым WorkerResult JSON."""
    monkeypatch.setenv("ENABLE_TEST_WORKER_TOOLS", "1")
    task = WorkerTask(
        task_id="task-test-sleep",
        tool_name="test.sleep",
        input_data={"sleep_seconds": 0},
    )
    completed = run_process(task.model_dump_json())

    result = WorkerResult.model_validate_json(completed.stdout)

    assert result.ok is True
    assert completed.stdout.strip().startswith("{")
    assert "[COM_DIAG]" not in completed.stdout
    assert "[COM_DIAG] step=test_sleep seconds=0.0" in completed.stderr


def test_unknown_tool_does_not_crash() -> None:
    """unknown tool не роняет дочерний процесс."""
    completed = run_process(make_task("unknown.tool").model_dump_json())
    result = WorkerResult.model_validate_json(completed.stdout)

    assert completed.returncode == 0
    assert result.ok is False
    assert result.error_type == "UNKNOWN_COM_TOOL"


def test_email_send_is_blocked() -> None:
    """email.send безопасно заблокирован в дочернем процессе."""
    completed = run_process(make_task("email.send").model_dump_json())
    result = WorkerResult.model_validate_json(completed.stdout)

    assert result.ok is False
    assert result.error_type == "SEND_DISABLED_FOR_SAFETY"


def test_email_create_draft_is_blocked() -> None:
    """email.create_draft безопасно заблокирован в дочернем процессе."""
    completed = run_process(make_task("email.create_draft").model_dump_json())
    result = WorkerResult.model_validate_json(completed.stdout)

    assert result.ok is False
    assert result.error_type == "DRAFT_DISABLED_FOR_SAFETY"


def test_invalid_input_json_returns_structured_error() -> None:
    """Невалидный input JSON возвращает структурированный WorkerResult."""
    completed = run_process("{bad json")
    result = WorkerResult.model_validate_json(completed.stdout)

    assert completed.returncode == 0
    assert result.ok is False
    assert result.error_type == "INVALID_WORKER_TASK"
