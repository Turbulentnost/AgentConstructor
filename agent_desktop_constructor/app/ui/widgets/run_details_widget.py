"""Страница деталей AgentRuntimeState."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.helpers import show_error
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState


class RunDetailsWidget(QWidget):
    """Показывает сохранённое состояние запуска."""

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу деталей запуска."""
        super().__init__(parent)
        self._container = container

        self.run_id_edit = QLineEdit()
        self.run_id_edit.setPlaceholderText("run_id")
        self.show_button = QPushButton("Показать состояние")
        self.details_output = QTextEdit()
        self.details_output.setReadOnly(True)

        top = QHBoxLayout()
        top.addWidget(QLabel("run_id:"))
        top.addWidget(self.run_id_edit)
        top.addWidget(self.show_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.details_output)

        self.show_button.clicked.connect(self.show_state)

    def show_state(self) -> None:
        """Загрузить и показать AgentRuntimeState."""
        run_id = self.run_id_edit.text().strip()
        if not run_id:
            show_error(self, "Нет run_id", "Введите run_id.")
            return
        try:
            state = self._container.agent_service.get_run_state(run_id)
        except Exception as exc:
            show_error(self, "Ошибка загрузки состояния", exc)
            return
        self.details_output.setPlainText(self._format_state(state))

    def _format_state(self, state: AgentRuntimeState) -> str:
        """Сформировать текстовое представление state."""
        pending = (
            state.pending_human_approval.model_dump(mode="json")
            if state.pending_human_approval
            else None
        )
        payload = {
            "run_id": state.run_id,
            "agent_id": state.agent_id,
            "status": state.status.value,
            "current_node_id": state.current_node_id,
            "step_counter": state.step_counter,
            "tool_call_counter": state.tool_call_counter,
            "errors": state.errors,
            "pending_human_approval": pending,
            "tool_results": [
                result.model_dump(mode="json") for result in state.tool_results
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

