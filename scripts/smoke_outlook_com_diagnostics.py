"""Ручная диагностика Outlook COM/MAPI через subprocess worker."""

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
    """Запустить ручную диагностику Outlook COM с timeout-защитой."""
    try:
        print("Outlook COM diagnostics smoke-check")
        print(f"OS: {platform.platform()}")
        print(f"Windows: {com_availability.is_windows()}")
        print(f"pywin32 available: {com_availability.is_pywin32_available()}")
        print(f"COM status: {com_availability.get_com_unavailable_reason()}")
        print()

        worker = SubprocessComWorker()
        task = WorkerTask(
            task_id="smoke-outlook-diagnostics",
            tool_name="outlook.diagnostics",
            input_data={},
            timeout_seconds=15,
        )
        result = worker.execute(task)
        print(f"ok: {result.ok}")
        print(f"error_type: {result.error_type}")
        print(f"error_message: {result.error_message}")

        if result.error_type == "WORKER_TIMEOUT":
            print("Outlook COM завис. Смотрите последний COM_DIAG шаг в error_message.")
            return 0

        diagnostics = (result.output_data or {}).get("diagnostics", {})
        steps = diagnostics.get("steps", [])
        recommendations = diagnostics.get("recommendations", [])
        print(f"diagnostics_ok: {diagnostics.get('ok')}")
        print("steps:")
        for step in steps:
            print(
                "- "
                f"{step.get('step')}: ok={step.get('ok')} "
                f"message={step.get('message')}"
            )
            if step.get("error_type"):
                print(
                    f"  error_type={step.get('error_type')} "
                    f"error_message={step.get('error_message')}"
                )

        print("recommendations:")
        for recommendation in recommendations:
            print(f"- {recommendation}")

        return 0
    except Exception as exc:
        print(f"Необработанная ошибка smoke-скрипта: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
