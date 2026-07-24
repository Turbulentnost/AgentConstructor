"""Frozen-friendly entrypoint desktop приложения."""

from __future__ import annotations

import multiprocessing
import runpy
import sys

from agent_desktop_constructor.app.ui.app import run_desktop_app
from agent_desktop_constructor.workers.com_worker_process import main as run_com_worker


def main() -> int:
    """Запустить desktop UI или изолированный COM-worker режим."""
    multiprocessing.freeze_support()
    if "--com-worker" in sys.argv:
        return run_com_worker()
    if "--agent-python-runner" in sys.argv:
        return _run_agent_python_script()
    return run_desktop_app()


def _run_agent_python_script() -> int:
    """Внутренний режим exe: выполнить .py скрипт агента без открытия UI."""
    marker_index = sys.argv.index("--agent-python-runner")
    try:
        script_path = sys.argv[marker_index + 1]
    except IndexError:
        print("Для --agent-python-runner нужен путь к .py файлу.", file=sys.stderr)
        return 2
    sys.argv = [script_path, *sys.argv[marker_index + 2 :]]
    runpy.run_path(script_path, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
