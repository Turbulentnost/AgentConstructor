"""Главное окно desktop UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QSplitter, QStackedWidget

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.teams_nav_sidebar import TeamsNavSidebar
from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
    AgentCreateWidget,
)
from agent_desktop_constructor.app.ui.widgets.agent_list_widget import AgentListWidget
from agent_desktop_constructor.app.ui.widgets.placeholder_page import (
    AnalyticsPlaceholderWidget,
    HomePlaceholderWidget,
)
from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget
from agent_desktop_constructor.app.ui.widgets.settings_widget import SettingsWidget


class MainWindow(QMainWindow):
    """Главное окно конструктора ИИ-агентов."""

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

        self.nav = TeamsNavSidebar()
        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: #0B0B14; }")

        self._home = HomePlaceholderWidget()
        self._agent_list = AgentListWidget(container)
        self._create_agent = AgentCreateWidget(container, auth_session=auth_session)
        self._run_list = RunListWidget(container)
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

        self._home.go_to_constructor.connect(
            lambda: self.nav.setCurrentIndex(self._CONSTRUCTOR_PAGE_INDEX)
        )
        if hasattr(self._create_agent, "agent_published"):
            self._create_agent.agent_published.connect(self._on_agent_published)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.nav)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

        self.nav.currentIndexChanged.connect(self._on_nav_changed)
        self.nav.setCurrentIndex(self._HOME_PAGE_INDEX)

    def _on_nav_changed(self, index: int) -> None:
        """Переключить страницу и обновить данные при входе на экран агентов."""
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        if index == self._AGENTS_PAGE_INDEX:
            QTimer.singleShot(0, self._agent_list, self._agent_list.refresh)

    def _on_agent_published(self) -> None:
        """После публикации перейти в каталог агентов."""
        self.nav.setCurrentIndex(self._AGENTS_PAGE_INDEX)
        QTimer.singleShot(0, self._agent_list, self._agent_list.refresh)
