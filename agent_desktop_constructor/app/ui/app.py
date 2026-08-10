"""Запуск PySide6 desktop UI."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
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


def run_desktop_app(config: AppConfig | None = None) -> int:
    """Собрать container, показать MainWindow и запустить event loop.

    «Выйти» не завершает процесс — снова открывается окно входа.
    Закрытие крестиком главного окна или «Выход» на логине завершает приложение.
    """
    app = create_qt_app()
    # Иначе при закрытии MainWindow Qt гасит весь процесс до показа логина.
    app.setQuitOnLastWindowClosed(False)

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

    ctx: dict = {"shell": None, "window": None}

    def _dispose_window() -> None:
        window = ctx.get("window")
        ctx["window"] = None
        if window is None:
            return
        window.hide()
        window.deleteLater()

    def _dispose_shell() -> None:
        shell = ctx.get("shell")
        ctx["shell"] = None
        if shell is None:
            return
        shell.hide()
        shell.close()
        shell.deleteLater()

    def _open_main(session, shell: LoginDialog) -> None:
        shell.show_loading(
            "Загружаем пользовательские данные",
            hint="Собираем интерфейс конструктора",
        )
        app.processEvents()
        container = build_application_container(app_config)
        app.processEvents()
        shell.show_loading(
            "Открываем конструктор",
            hint="Почти готово",
            cycle_phrases=False,
        )
        app.processEvents()

        window = MainWindow(container, auth_session=session)
        ctx["window"] = window
        window.logout_requested.connect(_on_logout)
        window.exit_requested.connect(_on_exit_app)

        if shell.isMaximized():
            window.showMaximized()
        else:
            window.setGeometry(shell.geometry())
            window.show()
        app.processEvents()
        _dispose_shell()

    def _on_logout() -> None:
        """Выйти из учётки → снова окно входа (приложение не гасим)."""
        clear_session()
        _dispose_window()
        # После deleteLater показать логин на следующем тике event loop.
        QTimer.singleShot(0, lambda: _show_login(force_login=True))

    def _on_exit_app() -> None:
        """Полный выход из приложения."""
        _dispose_window()
        _dispose_shell()
        app.quit()

    def _show_login(*, force_login: bool = False) -> None:
        _dispose_shell()
        shell = LoginDialog(proxy_url)
        ctx["shell"] = shell

        def on_authenticated() -> None:
            session = shell.session
            if session is None:
                return
            _open_main(session, shell)

        def on_rejected() -> None:
            _on_exit_app()

        shell.authenticated.connect(on_authenticated)
        shell.rejected.connect(on_rejected)

        if force_login:
            clear_session()
            shell.show_login_form()
            shell.show()
            app.processEvents()
            return

        shell.show_loading(
            "Загружаем пользовательские данные",
            hint="Проверяем сохранённую сессию",
        )
        shell.show()
        app.processEvents()

        session = _try_restore_session(proxy_url)
        if session is None:
            shell.show_login_form()
            app.processEvents()
            return
        _open_main(session, shell)

    _show_login(force_login=False)
    return app.exec()
