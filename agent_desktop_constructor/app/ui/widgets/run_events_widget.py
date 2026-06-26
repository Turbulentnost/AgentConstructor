"""Страница журнала событий запуска."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.core.models.run_events import AgentRunEvent
from agent_desktop_constructor.app.ui.helpers import (
    format_json_preview,
    set_table_rows,
    show_error,
)


class RunEventsWidget(QWidget):
    """Показывает AgentRunEvent по run_id."""

    HEADERS = ["created_at", "event_type", "node_id", "tool_name", "message"]

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу событий запуска."""
        super().__init__(parent)
        self._container = container
        self._events: list[AgentRunEvent] = []
        self._visible_events: list[AgentRunEvent] = []
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.show_events)

        self.run_id_edit = QLineEdit()
        self.run_id_edit.setPlaceholderText("run_id")
        self.event_type_filter = QComboBox()
        self.event_type_filter.addItem("Все", "")
        self.show_button = QPushButton("Показать события")
        self.refresh_button = QPushButton("Обновить")
        self.auto_refresh_checkbox = QCheckBox("Автообновление")
        self.status_label = QLabel("")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.details = QTextEdit()
        self.details.setReadOnly(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("run_id:"))
        top.addWidget(self.run_id_edit)
        top.addWidget(QLabel("event_type:"))
        top.addWidget(self.event_type_filter)
        top.addWidget(self.show_button)
        top.addWidget(self.refresh_button)
        top.addWidget(self.auto_refresh_checkbox)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(top)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.table)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.show_button.clicked.connect(self.show_events)
        self.refresh_button.clicked.connect(self.show_events)
        self.auto_refresh_checkbox.toggled.connect(self.set_auto_refresh)
        self.event_type_filter.currentIndexChanged.connect(self.render_events)
        self.table.itemSelectionChanged.connect(self.show_selected_event_details)

    def show_events(self) -> None:
        """Загрузить и показать события запуска."""
        run_id = self.run_id_edit.text().strip()
        if not run_id:
            show_error(self, "Нет run_id", "Введите run_id.")
            return
        try:
            self._events = self._container.agent_service.list_run_events(run_id)
        except Exception as exc:
            show_error(self, "Ошибка загрузки событий", exc)
            return
        self._refresh_event_type_filter()
        self.render_events()

    def render_events(self) -> None:
        """Показать события с учётом фильтра."""
        event_type = self.event_type_filter.currentData()
        events = [
            event
            for event in self._events
            if not event_type or event.event_type.value == event_type
        ]
        self.status_label.setText(
            "Для этого запуска событий пока нет."
            if not events
            else f"Найдено событий: {len(events)}"
        )
        rows = [
            [
                event.created_at.isoformat(),
                event.event_type.value,
                event.node_id or "",
                event.tool_name or "",
                event.message,
            ]
            for event in events
        ]
        self._visible_events = events
        set_table_rows(self.table, rows, self.HEADERS)
        if events:
            self.table.selectRow(0)
        else:
            self.details.clear()

    def set_auto_refresh(self, enabled: bool) -> None:
        """Включить или выключить автообновление событий."""
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def show_selected_event_details(self) -> None:
        """Показать details выбранного события."""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            self.details.clear()
            return
        row = selected[0].row()
        if row < 0 or row >= len(self._visible_events):
            self.details.clear()
            return
        event = self._visible_events[row]
        payload = event.model_dump(mode="json")
        self.details.setPlainText(format_json_preview(payload, max_chars=8000))

    def _refresh_event_type_filter(self) -> None:
        """Обновить список event_type без сброса выбранного значения без нужды."""
        current = self.event_type_filter.currentData()
        values = sorted({event.event_type.value for event in self._events})
        self.event_type_filter.blockSignals(True)
        self.event_type_filter.clear()
        self.event_type_filter.addItem("Все", "")
        for value in values:
            self.event_type_filter.addItem(value, value)
        index = self.event_type_filter.findData(current)
        self.event_type_filter.setCurrentIndex(index if index >= 0 else 0)
        self.event_type_filter.blockSignals(False)

