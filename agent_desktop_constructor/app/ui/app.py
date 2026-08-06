"""Запуск PySide6 desktop UI."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from agent_desktop_constructor.app.auth.client import (
    AuthClient,
    AuthClientError,
    clear_session,
    load_session,
)
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
from agent_desktop_constructor.app.ui.widgets.login_dialog import LoginDialog


def create_qt_app() -> QApplication:
    """Создать или вернуть существующий QApplication."""
    app = QApplication.instance()
    if app is not None:
        return app
    return QApplication(sys.argv)


def _resolve_proxy_url(config: AppConfig) -> str:
    return (config.llm_proxy_url or "").strip().rstrip("/")


def _try_restore_session(proxy_url: str):
    """Вернуть валидную сохранённую сессию или None."""
    session = load_session()
    if session is None:
        return None
    if not session.proxy_url:
        session.proxy_url = proxy_url
    try:
        user = AuthClient(session.proxy_url or proxy_url).me(session.access_token)
        session.user = user
        return session
    except AuthClientError:
        clear_session()
    except Exception:
        clear_session()
    return None


def _wait_for_login(shell: LoginDialog) -> bool:
    """Дождаться успешного входа без закрытия окна. False — выход."""
    loop = QEventLoop(shell)
    result = {"ok": False}

    def on_authenticated() -> None:
        result["ok"] = True
        loop.quit()

    def on_rejected() -> None:
        result["ok"] = False
        loop.quit()

    shell.authenticated.connect(on_authenticated)
    shell.rejected.connect(on_rejected)
    loop.exec()
    shell.authenticated.disconnect(on_authenticated)
    shell.rejected.disconnect(on_rejected)
    return bool(result["ok"] and shell.session is not None)


def _open_main_window(
    app: QApplication,
    shell: LoginDialog,
    app_config: AppConfig,
    auth_session,
) -> MainWindow:
    """Собрать MainWindow поверх экрана загрузки и закрыть shell."""
    shell.show_loading("Загрузка конструктора…")
    app.processEvents()

    container = build_application_container(app_config)
    app.processEvents()

    window = MainWindow(container, auth_session=auth_session)
    if shell.isMaximized():
        window.showMaximized()
    else:
        window.setGeometry(shell.geometry())
        window.show()
    app.processEvents()
    shell.close()
    return window


def run_desktop_app(config: AppConfig | None = None) -> int:
    """Собрать container, показать MainWindow и запустить event loop."""
    app = create_qt_app()
    load_dotenv_into_environ()
    app_config = config
    if app_config is None:
        try:
            if Path(DEFAULT_SETTINGS_PATH).exists() or getattr(sys, "frozen", False):
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

    proxy_url = _resolve_proxy_url(app_config)
    shell = LoginDialog(proxy_url)
    shell.show_loading("Проверка сессии…")
    shell.show()
    app.processEvents()

    auth_session = _try_restore_session(proxy_url)
    if auth_session is None:
        shell.show_login_form()
        app.processEvents()
        if not _wait_for_login(shell):
            shell.close()
            return 0
        auth_session = shell.session

    _open_main_window(app, shell, app_config, auth_session)
    return app.exec()
