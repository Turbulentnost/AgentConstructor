"""Главное окно desktop UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.teams_nav_sidebar import TeamsNavSidebar
from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
    AgentCreateWidget,
)
from agent_desktop_constructor.app.ui.widgets.agent_list_widget import (
    MODE_CATALOG,
    MODE_HOME,
    AgentListWidget,
)
from agent_desktop_constructor.app.ui.widgets.app_header_bar import AppHeaderBar
from agent_desktop_constructor.app.ui.widgets.placeholder_page import (
    AnalyticsPlaceholderWidget,
)
from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget
from agent_desktop_constructor.app.ui.widgets.settings_widget import SettingsWidget

_PAGE_CHROME: dict[int, tuple[str, str, bool]] = {
    0: ("Главная", "Закреплённые агенты", True),
    1: ("Доступные агенты", "Каталог с доступом по отделам", True),
    2: (
        "Создание агента",
        "Опишите задачу — система задаст вопросы и подготовит план",
        True,
    ),
    3: ("Мои задания", "История обращений к агентам", False),
    4: ("Аналитика", "Сводные метрики по агентам", False),
    5: ("Настройки", "Параметры приложения", False),
}


class MainWindow(QMainWindow):
    """Главное окно конструктора ИИ-агентов."""

    logout_requested = Signal()
    exit_requested = Signal()

    _HOME_PAGE_INDEX = 0
    _AGENTS_PAGE_INDEX = 1
    _CONSTRUCTOR_PAGE_INDEX = 2
    _TASKS_PAGE_INDEX = 3
    _ANALYTICS_PAGE_INDEX = 4
    _SETTINGS_PAGE_INDEX = 5

    def __init__(
        self,
        container: ApplicationContainer,
        parent=None,
        *,
        auth_session=None,
    ) -> None:
        """Создать окно с навигацией и страницами."""
        super().__init__(parent)
        self._container = container
        self._auth_session = auth_session
        self._logout_pending = False
        self.setWindowTitle("Конструктор ИИ-агентов")
        self.setMinimumSize(1280, 820)
        self.setStyleSheet(
            "* { font-family: 'Segoe UI'; }"
            "QMainWindow { background: #0B0B14; }"
            "QScrollBar:vertical { background:#0f0f1a; width:8px; margin:0; border:none; }"
            "QScrollBar::handle:vertical { background:#2a2a4a; border-radius:4px; min-height:28px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }"
            "QScrollBar:horizontal { background:#0f0f1a; height:8px; margin:0; border:none; }"
            "QScrollBar::handle:horizontal { background:#2a2a4a; border-radius:4px; min-width:28px; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }"
        )

        profile_name = "Пользователь"
        if auth_session is not None and getattr(auth_session, "user", None) is not None:
            profile_name = (
                auth_session.user.display_name
                or auth_session.user.login
                or profile_name
            )

        self.header = AppHeaderBar(profile_name=profile_name)
        self.header.create_clicked.connect(self._on_create_agent)
        self.header.settings_clicked.connect(self._open_profile_dialog)
        self.header.logout_clicked.connect(self._logout)

        self.nav = TeamsNavSidebar()
        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: #0B0B14; }")

        self._home = AgentListWidget(
            container, auth_session=auth_session, mode=MODE_HOME
        )
        self._agent_list = AgentListWidget(
            container, auth_session=auth_session, mode=MODE_CATALOG
        )
        self._create_agent = AgentCreateWidget(container, auth_session=auth_session)
        self._run_list = RunListWidget(container, auth_session=auth_session)
        self._analytics = AnalyticsPlaceholderWidget()
        self._settings = SettingsWidget()

        for widget in (
            self._home,
            self._agent_list,
            self._create_agent,
            self._run_list,
            self._analytics,
            self._settings,
        ):
            self.pages.addWidget(widget)

        if hasattr(self._create_agent, "agent_published"):
            self._create_agent.agent_published.connect(self._on_agent_published)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 12, 18, 0)
        content_layout.setSpacing(4)
        content_layout.addWidget(self.header, 0)
        content_layout.addWidget(self.pages, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.nav)
        splitter.addWidget(content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

        self.nav.currentIndexChanged.connect(self._on_nav_changed)
        self.nav.setCurrentIndex(self._HOME_PAGE_INDEX)
        self._apply_auth_session_to_header()
        self._apply_page_chrome(self._HOME_PAGE_INDEX)
        # Первый показ Главной (setCurrentIndex(0) может не эмитить сигнал).
        QTimer.singleShot(0, self._home.refresh)

    def _apply_page_chrome(self, index: int) -> None:
        title, subtitle, show_create = _PAGE_CHROME.get(
            index, ("Конструктор ИИ-агентов", "", True)
        )
        self.header.set_chrome(title, subtitle, show_create=show_create)

    def _apply_auth_session_to_header(self) -> None:
        session = self._auth_session
        if session is None:
            return
        name = session.user.display_name or session.user.login
        avatar_bytes = None
        if session.user.has_avatar and session.proxy_url and session.access_token:
            try:
                from agent_desktop_constructor.app.auth.client import AuthClient

                avatar_bytes = AuthClient(session.proxy_url).fetch_avatar(
                    session.access_token
                )
            except Exception:
                avatar_bytes = None
        self.header.set_profile(name, avatar_bytes)

    def _open_profile_dialog(self) -> None:
        if self._auth_session is None:
            return
        from agent_desktop_constructor.app.ui.widgets.profile_dialog import ProfileDialog

        dialog = ProfileDialog(self._auth_session, self)
        if dialog.exec():
            self._auth_session = dialog.session
            self._create_agent.set_auth_session(dialog.session)
            self._home.set_auth_session(dialog.session)
            self._agent_list.set_auth_session(dialog.session)
            self._run_list.set_auth_session(dialog.session)
            self._apply_auth_session_to_header()

    def _logout(self) -> None:
        from agent_desktop_constructor.app.auth.client import clear_session

        clear_session()
        self.request_logout()

    def _on_create_agent(self) -> None:
        """Перейти в конструктор и начать нового агента."""
        self.nav.setCurrentIndex(self._CONSTRUCTOR_PAGE_INDEX)
        if hasattr(self._create_agent, "reset_wizard_for_new_agent"):
            self._create_agent.reset_wizard_for_new_agent()
        elif hasattr(self._create_agent, "_reset_wizard_for_new_agent"):
            self._create_agent._reset_wizard_for_new_agent()

    def _on_nav_changed(self, index: int) -> None:
        """Переключить страницу и обновить данные при входе на экран агентов."""
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        self._apply_page_chrome(index)
        if index == self._HOME_PAGE_INDEX:
            QTimer.singleShot(0, self._home, self._home.refresh)
        elif index == self._AGENTS_PAGE_INDEX:
            QTimer.singleShot(0, self._agent_list, self._agent_list.refresh)
        elif index == self._TASKS_PAGE_INDEX:
            QTimer.singleShot(0, self._run_list, self._run_list.show_runs)

    def _on_agent_published(self) -> None:
        """После публикации перейти на Главную (агент автозакреплён)."""
        self.nav.setCurrentIndex(self._HOME_PAGE_INDEX)
        QTimer.singleShot(0, self._home, self._home.refresh)
        QTimer.singleShot(0, self._agent_list, self._agent_list.refresh)

    def request_logout(self) -> None:
        """Выйти из учётки — MainWindow скроет app.py и откроет окно входа."""
        if self._logout_pending:
            return
        self._logout_pending = True
        self._auth_session = None
        self.logout_requested.emit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Крестик — полный выход; «Выйти» из меню не должен сюда попадать."""
        if self._logout_pending:
            event.accept()
            return
        self.exit_requested.emit()
        event.accept()
