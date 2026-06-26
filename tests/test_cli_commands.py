"""Тесты CLI-команд без Windows/Outlook и без desktop UI."""

from __future__ import annotations

import sys

from agent_desktop_constructor.app.cli import commands
from agent_desktop_constructor.app.cli.main import main
from agent_desktop_constructor.workers.base import BaseWorker
from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask

TASK_CONTROL_REQUEST = "Создай агента, который проверяет Outlook и находит поручения"


class CliFakeWorker(BaseWorker):
    """Fake worker для CLI-тестов без реального Outlook COM."""

    def __init__(self) -> None:
        """Создать worker со списком полученных задач."""
        self.tasks: list[WorkerTask] = []

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Вернуть стабильные worker-ответы для CLI."""
        self.tasks.append(task)
        if task.tool_name == "outlook.diagnostics":
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data={
                    "diagnostics": {
                        "ok": True,
                        "steps": [
                            {
                                "step": "check_windows",
                                "ok": True,
                                "message": "Windows доступен",
                            }
                        ],
                        "recommendations": ["Fake diagnostics OK"],
                    }
                },
            )
        if task.tool_name == "outlook.search_mail":
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data={"messages": [{"id": "mail-1"}], "count": 1},
            )
        if task.tool_name == "outlook.read_calendar":
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data={"events": [{"id": "event-1"}], "count": 1},
            )
        if task.tool_name == "outlook.read_tasks":
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="OUTLOOK_TOOL_NOT_IMPLEMENTED",
                error_message="Outlook tasks пока не реализованы",
            )
        if task.tool_name == "email.send":
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="SEND_DISABLED_FOR_SAFETY",
                error_message="Отправка писем заблокирована в тесте",
            )
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type="UNKNOWN_COM_TOOL",
            error_message="Неизвестный fake tool",
        )


def test_build_agent_prints_agent_spec(capsys) -> None:
    """build-agent строит AgentSpec и печатает его поля."""
    exit_code = commands.build_agent(TASK_CONTROL_REQUEST)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "=== Агент ===" in output
    assert "Агент контроля поручений" in output
    assert "outlook.search_mail" in output
    assert "=== Граф ===" in output
    assert "=== Вызванные инструменты ===" not in output
    assert "=== Результат запуска ===" not in output


def test_run_fake_completes_without_errors(capsys) -> None:
    """run-fake завершает task-control агента без ошибок."""
    exit_code = commands.run_fake(TASK_CONTROL_REQUEST)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Статус: completed" in output
    assert "Отчёт по поручениям" in output


def test_run_fake_calls_expected_fake_tools(capsys) -> None:
    """run-fake вызывает ожидаемые fake tools через Runtime."""
    commands.run_fake(TASK_CONTROL_REQUEST)

    output = capsys.readouterr().out
    assert "outlook.search_mail: ok" in output
    assert "outlook.read_calendar: ok" in output
    assert "outlook.read_tasks: ok" in output
    assert "report.build_task_report: ok" in output


def test_test_send_block_shows_two_level_blocking(capsys) -> None:
    """test-send-block показывает gateway и worker safe-mode блокировку."""
    exit_code = commands.test_send_block(worker_factory=CliFakeWorker)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "gateway_without_approval: HUMAN_APPROVAL_REQUIRED" in output
    assert "gateway_with_approval: SEND_DISABLED_FOR_SAFETY" in output
    assert "real_send_executed: false" in output


def test_diagnose_outlook_command_builds_with_fake_worker(capsys) -> None:
    """diagnose-outlook можно выполнить без реального COM через fake worker."""
    exit_code = commands.diagnose_outlook(worker_factory=CliFakeWorker)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "=== Шаги диагностики ===" in output
    assert "check_windows" in output


def test_cli_modules_import_without_pyside6() -> None:
    """CLI-модули не импортируют PySide6."""
    assert "PySide6" not in sys.modules
    assert not any(module_name.startswith("PySide6.") for module_name in sys.modules)


def test_cli_modules_do_not_import_pywin32_directly() -> None:
    """CLI-модули не импортируют pywin32 напрямую."""
    assert "pythoncom" not in sys.modules
    assert "win32com" not in sys.modules
    assert not any(module_name.startswith("win32com.") for module_name in sys.modules)


def test_cli_modules_do_not_import_redis_or_celery() -> None:
    """CLI-модули не импортируют Redis и Celery."""
    assert "redis" not in sys.modules
    assert "celery" not in sys.modules
    assert not any(module_name.startswith("redis.") for module_name in sys.modules)
    assert not any(module_name.startswith("celery.") for module_name in sys.modules)


def test_run_outlook_readonly_works_with_fake_worker(capsys) -> None:
    """run-outlook-readonly тестируется через fake worker без Outlook."""
    exit_code = commands.run_outlook_readonly(
        TASK_CONTROL_REQUEST,
        worker_factory=CliFakeWorker,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "outlook.search_mail: ok" in output
    assert "outlook.read_calendar: ok" in output
    assert "outlook.read_tasks: error" in output
    assert "OUTLOOK_TOOL_NOT_IMPLEMENTED" in output
    assert "report.build_task_report: ok" in output


def test_main_dispatches_build_agent(capsys) -> None:
    """main dispatch работает через argparse."""
    exit_code = main(["build-agent", TASK_CONTROL_REQUEST])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Агент контроля поручений" in output

