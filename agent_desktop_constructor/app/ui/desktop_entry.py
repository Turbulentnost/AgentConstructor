"""Frozen-friendly entrypoint desktop приложения."""

from __future__ import annotations

import multiprocessing
import sys

from agent_desktop_constructor.app.ui.app import run_desktop_app
from agent_desktop_constructor.workers.com_worker_process import main as run_com_worker


def main() -> int:
    """Запустить desktop UI или изолированный COM-worker режим."""
    multiprocessing.freeze_support()
    if "--com-worker" in sys.argv:
        return run_com_worker()
    return run_desktop_app()


if __name__ == "__main__":
    raise SystemExit(main())
