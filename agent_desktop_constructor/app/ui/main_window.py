"""Главное окно desktop UI."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
)
from PySide6.QtCore import Qt

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
    AgentCreateWidget,
)
from agent_desktop_constructor.app.ui.widgets.agent_list_widget import AgentListWidget
from agent_desktop_constructor.app.ui.widgets.approval_queue_widget import (
    ApprovalQueueWidget,
)
from agent_desktop_constructor.app.ui.widgets.log_panel_widget import LogPanelWidget
from agent_desktop_constructor.app.ui.widgets.run_details_widget import RunDetailsWidget
from agent_desktop_constructor.app.ui.widgets.run_events_widget import RunEventsWidget
from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget
from agent_desktop_constructor.app.ui.widgets.settings_widget import SettingsWidget


class MainWindow(QMainWindow):
    """Главное окно конструктора ИИ-агентов."""

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

        self.menu = QListWidget()
        self.pages = QStackedWidget()
        self.log_panel = LogPanelWidget()

        page_specs = [
            ("Агенты", AgentListWidget(container)),
            ("Создать агента", AgentCreateWidget(container)),
            ("Запуски", RunListWidget(container)),
            ("Состояние запуска", RunDetailsWidget(container)),
            ("События", RunEventsWidget(container)),
            ("Подтверждения", ApprovalQueueWidget(container)),
            ("Настройки", SettingsWidget()),
            ("Журнал", self.log_panel),
        ]

        for title, widget in page_specs:
            self.menu.addItem(QListWidgetItem(title))
            self.pages.addWidget(widget)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.menu)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 5)
        self.setCentralWidget(splitter)

        self.menu.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.menu.setCurrentRow(0)

