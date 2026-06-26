"""Запуск PySide6 desktop UI AgentConstructor."""

from __future__ import annotations

import sys


def main() -> int:
    """Запустить desktop-приложение."""
    try:
        from agent_desktop_constructor.app.ui.app import run_desktop_app
    except ImportError as exc:
        if "PySide6" in str(exc):
            print(
                "PySide6 не установлен. Установите зависимости проекта "
                "или выполните: pip install PySide6",
                file=sys.stderr,
            )
            return 1
        raise

    return run_desktop_app()


if __name__ == "__main__":
    raise SystemExit(main())

