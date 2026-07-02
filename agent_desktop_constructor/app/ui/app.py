"""Запуск PySide6 desktop UI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pathlib import Path

from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import (
    AppConfig,
    apply_llm_api_key_from_env,
    load_app_config_from_env,
    load_dotenv_into_environ,
)
from agent_desktop_constructor.app.core.settings import (
    DEFAULT_SETTINGS_PATH,
    load_settings,
)
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
    load_dotenv_into_environ()
    app_config = config
    if app_config is None:
        try:
            if Path(DEFAULT_SETTINGS_PATH).exists():
                app_config = load_settings()
            else:
                app_config = load_app_config_from_env()
        except Exception as exc:
            show_error(
                None,
                "Ошибка настроек",
                f"{exc}\nБудут использованы настройки по умолчанию.",
            )
            app_config = AppConfig()
    app_config = apply_llm_api_key_from_env(app_config)
    container = build_application_container(app_config)
    window = MainWindow(container)
    window.show()
    return app.exec()

