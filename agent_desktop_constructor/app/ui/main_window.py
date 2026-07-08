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
from agent_desktop_constructor.app.ui.widgets.run_events_widget import RunEventsWidget
from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget
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
        self.setMinimumSize(1280, 820)
        self.setStyleSheet(
            "* { font-family: 'Segoe UI'; }"
            "QMainWindow { background: #06101d; }"
            "QScrollBar:vertical { background:#071426; width:8px; margin:0; border:none; }"
            "QScrollBar::handle:vertical { background:#1b3b61; border-radius:4px; min-height:28px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }"
            "QScrollBar:horizontal { background:#071426; height:8px; margin:0; border:none; }"
            "QScrollBar::handle:horizontal { background:#1b3b61; border-radius:4px; min-width:28px; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }"
        )

        self.nav = TeamsNavSidebar()
        self.pages = QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: #06101d; }")
        self._agent_list = AgentListWidget(container)
        self._create_agent = AgentCreateWidget(container)
        self._run_list = RunListWidget(container)
        self._run_events = RunEventsWidget(container)

        for _title, widget in [
            ("Агенты", self._agent_list),
            ("Создать агента", self._create_agent),
            ("Запуски", self._run_list),
            ("События", self._run_events),
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
