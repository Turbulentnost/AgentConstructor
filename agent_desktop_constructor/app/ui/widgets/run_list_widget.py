"""Страница списка и запуска AgentRun."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
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
from PySide6.QtCore import Qt

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.helpers import set_table_rows, show_error, show_info
from agent_desktop_constructor.app.ui.workers.agent_run_thread_manager import (
    AgentRunThreadManager,
)
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState


class RunListWidget(QWidget):
    """Показывает запуски агента и запускает сохранённого агента."""

    HEADERS = [
        "run_id",
        "status",
        "current_node_id",
        "step_counter",
        "tool_call_counter",
        "pending approval",
        "errors",
    ]

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу запусков."""
        super().__init__(parent)
        self._container = container
        self._states: list[AgentRuntimeState] = []
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.show_runs)
        self._run_manager = AgentRunThreadManager(self)

        self.agent_id_edit = QLineEdit()
        self.agent_id_edit.setPlaceholderText("agent_id")
        self.show_runs_button = QPushButton("Показать запуски")
        self.refresh_button = QPushButton("Обновить")
        self.run_agent_button = QPushButton("Запустить агента")
        self.open_events_button = QPushButton("Открыть события")
        self.open_state_button = QPushButton("Открыть состояние")
        self.auto_refresh_checkbox = QCheckBox("Автообновление")
        self.status_label = QLabel("")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.details = QTextEdit()
        self.details.setReadOnly(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("agent_id:"))
        top.addWidget(self.agent_id_edit)
        top.addWidget(self.show_runs_button)
        top.addWidget(self.refresh_button)
        top.addWidget(self.run_agent_button)
        top.addWidget(self.open_events_button)
        top.addWidget(self.open_state_button)
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

        self.show_runs_button.clicked.connect(self.show_runs)
        self.refresh_button.clicked.connect(self.show_runs)
        self.run_agent_button.clicked.connect(self.run_agent)
        self.open_events_button.clicked.connect(self.open_events_hint)
        self.open_state_button.clicked.connect(self.open_state_hint)
        self.auto_refresh_checkbox.toggled.connect(self.set_auto_refresh)
        self.table.itemSelectionChanged.connect(self.show_selected_run_details)
        self._run_manager.run_started.connect(self._on_run_started)
        self._run_manager.run_progress.connect(self.status_label.setText)
        self._run_manager.run_completed.connect(self._on_run_completed)
        self._run_manager.run_failed.connect(self._on_run_failed)

    def show_runs(self) -> None:
        """Показать запуски указанного агента."""
        agent_id = self.agent_id_edit.text().strip()
        if not agent_id:
            show_error(self, "Нет agent_id", "Введите agent_id.")
            return
        try:
            states = self._container.agent_service.list_runs(agent_id)
        except Exception as exc:
            show_error(self, "Ошибка загрузки запусков", exc)
            return

        self._states = states
        self.status_label.setText(
            "У этого агента пока нет запусков."
            if not states
            else f"Найдено запусков: {len(states)}"
        )
        rows = [
            [
                state.run_id,
                state.status.value,
                state.current_node_id or "",
                str(state.step_counter),
                str(state.tool_call_counter),
                "да" if state.pending_human_approval is not None else "нет",
                "; ".join(state.errors),
            ]
            for state in states
        ]
        set_table_rows(self.table, rows, self.HEADERS)
        if states:
            self.table.selectRow(0)
        else:
            self.details.clear()

    def run_agent(self) -> None:
        """Запустить сохранённого агента через service-слой."""
        agent_id = self.agent_id_edit.text().strip()
        if not agent_id:
            show_error(self, "Нет agent_id", "Введите agent_id.")
            return
        if self._run_manager.is_running():
            show_error(self, "Запуск уже выполняется", "Дождитесь завершения запуска.")
            return
        self.run_agent_button.setEnabled(False)
        self.status_label.setText("Агент запускается...")
        self._run_manager.start_agent_by_id(agent_id, self._container.agent_service)

    def _on_run_started(self, agent_id: str) -> None:
        """Показать старт фонового запуска."""
        self.status_label.setText(f"Агент запускается: {agent_id}")

    def _on_run_completed(self, state: AgentRuntimeState) -> None:
        """Обработать успешное завершение фонового запуска."""
        self.run_agent_button.setEnabled(True)
        message = f"Запуск завершён со статусом: {state.status.value}"
        if state.errors:
            message += "\nОшибки:\n" + "\n".join(state.errors)
        if state.pending_human_approval is not None:
            message += "\n\nЗапуск ожидает подтверждения человека."
        if any("WORKER_TIMEOUT" in error for error in state.errors):
            message += (
                "\n\nOutlook COM не ответил за заданное время. "
                "Проверьте Outlook, профиль и модальные окна."
            )
        show_info(self, "Результат запуска", message)
        self.show_runs()

    def _on_run_failed(self, message: str) -> None:
        """Обработать ошибку фонового запуска."""
        self.run_agent_button.setEnabled(True)
        if "WORKER_TIMEOUT" in message:
            message = (
                "Outlook COM не ответил за заданное время. "
                "Проверьте Outlook, профиль и модальные окна."
            )
        show_error(self, "Ошибка запуска агента", message)

    def set_auto_refresh(self, enabled: bool) -> None:
        """Включить или выключить автообновление списка запусков."""
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def show_selected_run_details(self) -> None:
        """Показать карточку выбранного запуска."""
        state = self._selected_state()
        if state is None:
            self.details.clear()
            return
        pending = state.pending_human_approval
        lines = [
            f"run_id: {state.run_id}",
            f"status: {state.status.value}",
            f"current_node_id: {state.current_node_id}",
            f"step_counter: {state.step_counter}",
            f"tool_call_counter: {state.tool_call_counter}",
            "",
            "errors:",
            *[f"- {error}" for error in state.errors],
            "",
            "pending_human_approval:",
            (
                pending.model_dump_json(indent=2)
                if pending is not None
                else "нет"
            ),
        ]
        self.details.setPlainText("\n".join(lines))

    def open_events_hint(self) -> None:
        """Показать run_id для страницы событий."""
        self._show_run_id_hint("События запуска")

    def open_state_hint(self) -> None:
        """Показать run_id для страницы состояния."""
        self._show_run_id_hint("Состояние запуска")

    def _show_run_id_hint(self, title: str) -> None:
        """Показать выбранный run_id."""
        state = self._selected_state()
        if state is None:
            show_error(self, "Запуск не выбран", "Выберите запуск в таблице.")
            return
        show_info(self, title, f"Используйте run_id:\n{state.run_id}")

    def _selected_state(self) -> AgentRuntimeState | None:
        """Вернуть выбранный запуск."""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._states):
            return None
        return self._states[row]

