"""Временный пробник диапазонов Outlook COM через subprocess worker."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_desktop_constructor.workers.models import WorkerTask
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def main() -> int:
    worker = SubprocessComWorker()
    for days in (7, 30, 365):
        task = WorkerTask(
            task_id="m",
            tool_name="outlook.search_mail",
            input_data={
                "folder": "Inbox",
                "days": days,
                "query": None,
                "max_results": 5,
                "max_scan_items": 300,
            },
            timeout_seconds=40,
        )
        result = worker.execute(task)
        output = result.output_data or {}
        print(
            f"mail days={days} ok={result.ok} err={result.error_type} "
            f"count={output.get('count')} scanned={output.get('scanned_count')} "
            f"msg={result.error_message}"
        )
    for days_forward in (7, 30, 365):
        task = WorkerTask(
            task_id="c",
            tool_name="outlook.read_calendar",
            input_data={
                "days_forward": days_forward,
                "max_results": 5,
                "max_scan_items": 300,
            },
            timeout_seconds=40,
        )
        result = worker.execute(task)
        output = result.output_data or {}
        print(
            f"cal days_forward={days_forward} ok={result.ok} err={result.error_type} "
            f"count={output.get('count')} scanned={output.get('scanned_count')} "
            f"msg={result.error_message}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
