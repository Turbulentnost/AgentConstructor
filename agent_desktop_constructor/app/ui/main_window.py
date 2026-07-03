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
from agent_desktop_constructor.app.ui.widgets.log_panel_widget import LogPanelWidget
from agent_desktop_constructor.app.ui.widgets.settings_widget import SettingsWidget


class MainWindow(QMainWindow):
    """Главное окно конструктора ИИ-агентов."""

    _AGENTS_PAGE_INDEX = 0

    def __init__(
        self,
        container: ApplicationContainer,
        parent=None,
    ) -> None:
        """Создать окно с навигацией и страницами."""
        super().__init__(parent)
        self._container = container
        self.setWindowTitle("Конструктор ИИ-агентов")
        self.setMinimumSize(1200, 800)
        self.setStyleSheet("QMainWindow { background: #0b0b0d; }")

        self.nav = TeamsNavSidebar()
        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: #0b0b0d; }")
        self.log_panel = LogPanelWidget()
        self._agent_list = AgentListWidget(container)
        self._create_agent = AgentCreateWidget(container)

        for _title, widget in [
            ("Агенты", self._agent_list),
            ("Создать агента", self._create_agent),
            ("Журнал", self.log_panel),
            ("Настройки", SettingsWidget()),
        ]:
            self.pages.addWidget(widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.nav)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

        self.nav.currentIndexChanged.connect(self._on_nav_changed)
        self.nav.setCurrentIndex(self._AGENTS_PAGE_INDEX)

    def _on_nav_changed(self, index: int) -> None:
        """Переключить страницу и обновить данные при входе на экран агентов."""
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        if index == self._AGENTS_PAGE_INDEX:
            QTimer.singleShot(0, self._agent_list, self._agent_list.refresh)
