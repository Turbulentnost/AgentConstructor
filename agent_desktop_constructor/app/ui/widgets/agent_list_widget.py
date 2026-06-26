"""Страница списка сохранённых агентов."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
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
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState


class AgentListWidget(QWidget):
    """Показывает список сохранённых агентов из service-слоя."""

    HEADERS = ["ID", "Название", "Описание", "Цель", "Инструментов", "Узлов графа"]

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу списка агентов."""
        super().__init__(parent)
        self._container = container
        self._agents: list[AgentSpec] = []
        self._run_manager = AgentRunThreadManager(self)

        self.refresh_button = QPushButton("Обновить")
        self.run_selected_button = QPushButton("Запустить выбранного агента")
        self.show_runs_button = QPushButton("Показать запуски")
        self.status_label = QLabel("")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.details = QTextEdit()
        self.details.setReadOnly(True)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.run_selected_button)
        buttons.addWidget(self.show_runs_button)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addLayout(buttons)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.table)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.refresh_button.clicked.connect(self.refresh)
        self.run_selected_button.clicked.connect(self.run_selected_agent)
        self.show_runs_button.clicked.connect(self.show_selected_runs_hint)
        self.table.itemSelectionChanged.connect(self.show_selected_agent_details)
        self._run_manager.run_started.connect(self._on_run_started)
        self._run_manager.run_progress.connect(self.status_label.setText)
        self._run_manager.run_completed.connect(self._on_run_completed)
        self._run_manager.run_failed.connect(self._on_run_failed)

    def refresh(self) -> None:
        """Перечитать список агентов."""
        try:
            agents = self._container.agent_service.list_agents()
        except Exception as exc:
            show_error(self, "Ошибка загрузки агентов", exc)
            return

        self._agents = agents
        if not agents:
            self.status_label.setText("Сохранённых агентов пока нет.")
            set_table_rows(self.table, [], self.HEADERS)
            self.details.clear()
            return
        self.status_label.setText(f"Найдено агентов: {len(agents)}")

        rows = [
            [
                agent.agent_id,
                agent.name,
                agent.description,
                agent.goal.main_goal,
                str(len(agent.tools)),
                str(len(agent.graph_nodes)),
            ]
            for agent in agents
        ]
        set_table_rows(self.table, rows, self.HEADERS)
        self.table.selectRow(0)

    def show_selected_agent_details(self) -> None:
        """Показать карточку выбранного агента."""
        agent = self._selected_agent()
        if agent is None:
            self.details.clear()
            return
        self.details.setPlainText(self._format_agent_details(agent))

    def run_selected_agent(self) -> None:
        """Запустить выбранного агента через service."""
        agent = self._selected_agent()
        if agent is None:
            show_error(self, "Агент не выбран", "Выберите агента в таблице.")
            return
        if self._run_manager.is_running():
            show_error(self, "Запуск уже выполняется", "Дождитесь завершения запуска.")
            return
        self.run_selected_button.setEnabled(False)
        self.status_label.setText("Агент запускается...")
        self._run_manager.start_agent_by_id(agent.agent_id, self._container.agent_service)

    def _on_run_started(self, agent_id: str) -> None:
        """Показать старт фонового запуска."""
        self.status_label.setText(f"Агент запускается: {agent_id}")

    def _on_run_completed(self, state: AgentRuntimeState) -> None:
        """Обработать завершение фонового запуска."""
        self.run_selected_button.setEnabled(True)
        message = f"run_id: {state.run_id}\nstatus: {state.status.value}"
        if state.errors:
            message += "\nОшибки:\n" + "\n".join(state.errors)
        if state.pending_human_approval is not None:
            message += "\n\nЗапуск ожидает подтверждения человека."
        if any("WORKER_TIMEOUT" in error for error in state.errors):
            message += (
                "\n\nOutlook COM не ответил за заданное время. "
                "Проверьте Outlook, профиль и модальные окна."
            )
        show_info(self, "Агент запущен", message)

    def _on_run_failed(self, message: str) -> None:
        """Обработать ошибку фонового запуска."""
        self.run_selected_button.setEnabled(True)
        if "WORKER_TIMEOUT" in message:
            message = (
                "Outlook COM не ответил за заданное время. "
                "Проверьте Outlook, профиль и модальные окна."
            )
        show_error(self, "Ошибка запуска агента", message)

    def show_selected_runs_hint(self) -> None:
        """Показать agent_id для страницы запусков."""
        agent = self._selected_agent()
        if agent is None:
            show_error(self, "Агент не выбран", "Выберите агента в таблице.")
            return
        show_info(
            self,
            "Запуски агента",
            f"Откройте страницу 'Запуски' и используйте agent_id:\n{agent.agent_id}",
        )

    def _selected_agent(self) -> AgentSpec | None:
        """Вернуть выбранного агента."""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._agents):
            return None
        return self._agents[row]

    def _format_agent_details(self, agent: AgentSpec) -> str:
        """Сформировать текст карточки агента."""
        lines = [
            f"ID: {agent.agent_id}",
            f"Название: {agent.name}",
            f"Описание: {agent.description}",
            f"Цель: {agent.goal.main_goal}",
            "",
            "Критерии успеха:",
            *[f"- {item}" for item in agent.goal.success_criteria],
            "",
            "Запрещённые действия:",
            *[f"- {item}" for item in agent.goal.forbidden_actions],
            "",
            "Требования к данным:",
        ]
        lines.extend(
            [f"- {item.name}: {item.description}" for item in agent.data_requirements]
            or ["- нет"]
        )
        lines.append("")
        lines.append("Разрешённые инструменты:")
        lines.extend(
            f"- {tool.tool_name}: {tool.action_level.value}, "
            f"approval={tool.requires_human_approval}, allowed={tool.allowed}"
            for tool in agent.tools
        )
        lines.append("")
        lines.append("Граф узлов:")
        lines.extend(
            f"- {node.node_id} [{node.node_type.value}] "
            f"tool={node.tool_name or '-'} -> {node.next_on_success or 'конец'}"
            for node in agent.graph_nodes
        )
        return "\n".join(lines)

