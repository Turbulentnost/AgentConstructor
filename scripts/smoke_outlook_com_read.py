"""Ручная smoke-проверка read-only Outlook COM worker-а."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_desktop_constructor.workers import com_availability
from agent_desktop_constructor.workers.models import WorkerTask
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def main() -> int:
    """Запустить ручную read-only проверку Outlook COM."""
    try:
        print("Outlook COM read smoke-check")
        print(f"OS: {platform.platform()}")
        print(f"Windows: {com_availability.is_windows()}")
        print(f"pywin32 available: {com_availability.is_pywin32_available()}")
        print(f"COM status: {com_availability.get_com_unavailable_reason()}")
        print()

        worker = SubprocessComWorker()
        _print_mail_result(worker)
        print()
        _print_calendar_result(worker)
        print()
        print("Проверка завершена. Smoke-скрипт выполнял только read-only операции.")
        return 0
    except Exception as exc:
        print(f"Необработанная ошибка smoke-скрипта: {exc}", file=sys.stderr)
        return 1


def _print_mail_result(worker: SubprocessComWorker) -> None:
    """Прочитать и вывести краткую информацию по письмам."""
    task = WorkerTask(
        task_id="smoke-outlook-search-mail",
        tool_name="outlook.search_mail",
        input_data={
            "folder": "Inbox",
            "days": 7,
            "query": None,
            "max_results": 5,
            "max_scan_items": 100,
        },
        timeout_seconds=20,
    )
    result = worker.execute(task)
    output_data = result.output_data or {}
    messages = output_data.get("messages", [])

    print("== Inbox messages ==")
    print(f"ok: {result.ok}")
    print(f"error_type: {result.error_type}")
    print(f"error_message: {result.error_message}")
    if result.error_type == "WORKER_TIMEOUT":
        print("Outlook COM завис при чтении писем. Последний COM_DIAG шаг есть в error_message.")
    print(f"count: {output_data.get('count', 0)}")
    for index, message in enumerate(messages[:5], start=1):
        print(f"{index}. subject: {_truncate(message.get('subject'))}")
        print(f"   sender: {_truncate(message.get('sender'))}")
        print(f"   received_at: {_truncate(message.get('received_at'))}")
        print(f"   body_preview: {_truncate(message.get('body_preview'), 120)}")


def _print_calendar_result(worker: SubprocessComWorker) -> None:
    """Прочитать и вывести краткую информацию по календарю."""
    task = WorkerTask(
        task_id="smoke-outlook-read-calendar",
        tool_name="outlook.read_calendar",
        input_data={
            "days_forward": 7,
            "max_results": 5,
            "max_scan_items": 100,
        },
        timeout_seconds=20,
    )
    result = worker.execute(task)
    output_data = result.output_data or {}
    events = output_data.get("events", [])

    print("== Calendar events ==")
    print(f"ok: {result.ok}")
    print(f"error_type: {result.error_type}")
    print(f"error_message: {result.error_message}")
    if result.error_type == "WORKER_TIMEOUT":
        print("Outlook COM завис при чтении календаря. Последний COM_DIAG шаг есть в error_message.")
    print(f"count: {output_data.get('count', 0)}")
    for index, event in enumerate(events[:5], start=1):
        print(f"{index}. subject: {_truncate(event.get('subject'))}")
        print(f"   start: {_truncate(event.get('start'))}")
        print(f"   end: {_truncate(event.get('end'))}")
        print(f"   location: {_truncate(event.get('location'))}")
        print(f"   organizer: {_truncate(event.get('organizer'))}")


def _truncate(value: object, limit: int = 120) -> str:
    """Ограничить вывод диагностических данных в консоль."""
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
