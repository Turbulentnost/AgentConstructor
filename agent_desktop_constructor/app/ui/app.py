"""Запуск PySide6 desktop UI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.settings import load_settings
from agent_desktop_constructor.app.ui.helpers import show_error
from agent_desktop_constructor.app.ui.main_window import MainWindow


def create_qt_app() -> QApplication:
    """Создать или вернуть существующий QApplication."""
    app = QApplication.instance()
    if app is not None:
        return app
    return QApplication(sys.argv)


def run_desktop_app(config: AppConfig | None = None) -> int:
    """Собрать container, показать MainWindow и запустить event loop."""
    app = create_qt_app()
    app_config = config
    if app_config is None:
        try:
            app_config = load_settings()
        except Exception as exc:
            show_error(
                None,
                "Ошибка настроек",
                f"{exc}\nБудут использованы настройки по умолчанию.",
            )
            app_config = AppConfig()
    container = build_application_container(app_config)
    window = MainWindow(container)
    window.show()
    return app.exec()

