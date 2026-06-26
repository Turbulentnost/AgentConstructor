"""Страница очереди подтверждений человека."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
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

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.core.models.human_approval import HumanApprovalRecord
from agent_desktop_constructor.app.ui.helpers import set_table_rows, show_error, show_info


class ApprovalQueueWidget(QWidget):
    """Показывает pending approvals и продолжает запуск по решению человека."""

    HEADERS = [
        "approval_id",
        "run_id",
        "agent_id",
        "node_id",
        "tool_name",
        "question",
        "created_at",
    ]

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу подтверждений."""
        super().__init__(parent)
        self._container = container
        self._records: list[HumanApprovalRecord] = []
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)

        self.refresh_button = QPushButton("Обновить")
        self.approve_button = QPushButton("Подтвердить")
        self.reject_button = QPushButton("Отклонить")
        self.auto_refresh_checkbox = QCheckBox("Автообновление")
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("Комментарий к отказу")
        self.status_label = QLabel("")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.details = QTextEdit()
        self.details.setReadOnly(True)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.comment_edit)
        buttons.addWidget(self.auto_refresh_checkbox)

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
        self.approve_button.clicked.connect(self.approve_selected)
        self.reject_button.clicked.connect(self.reject_selected)
        self.auto_refresh_checkbox.toggled.connect(self.set_auto_refresh)
        self.table.itemSelectionChanged.connect(self.show_selected_approval_details)

    def refresh(self) -> None:
        """Перечитать pending approvals."""
        try:
            records = self._container.agent_service.list_pending_approvals()
        except Exception as exc:
            show_error(self, "Ошибка загрузки подтверждений", exc)
            return

        self._records = records
        self.status_label.setText(
            "Ожидающих подтверждений нет."
            if not records
            else f"Ожидающих подтверждений: {len(records)}"
        )
        rows = [
            [
                record.approval_id,
                record.run_id,
                record.agent_id,
                record.node_id,
                record.tool_name or "",
                record.question,
                record.created_at.isoformat(),
            ]
            for record in records
        ]
        set_table_rows(self.table, rows, self.HEADERS)
        if records:
            self.table.selectRow(0)
        else:
            self.details.clear()

    def approve_selected(self) -> None:
        """Подтвердить выбранный approval и продолжить Runtime."""
        approval_id = self._selected_approval_id()
        if approval_id is None:
            return
        try:
            state = self._container.agent_service.resume_run_by_approval(
                approval_id,
                approved=True,
            )
        except Exception as exc:
            show_error(self, "Ошибка подтверждения", exc)
            return
        self.refresh()
        self._show_result(state.run_id, state.status.value, state.errors)

    def reject_selected(self) -> None:
        """Отклонить выбранный approval и продолжить Runtime."""
        approval_id = self._selected_approval_id()
        if approval_id is None:
            return
        try:
            state = self._container.agent_service.resume_run_by_approval(
                approval_id,
                approved=False,
                comment=self.comment_edit.text().strip() or None,
            )
        except Exception as exc:
            show_error(self, "Ошибка отказа", exc)
            return
        self.refresh()
        self._show_result(state.run_id, state.status.value, state.errors)

    def set_auto_refresh(self, enabled: bool) -> None:
        """Включить или выключить автообновление очереди."""
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def show_selected_approval_details(self) -> None:
        """Показать карточку выбранного approval."""
        record = self._selected_record()
        if record is None:
            self.details.clear()
            return
        lines = [
            f"question: {record.question}",
            "options:",
            *[f"- {option}" for option in record.options],
            "",
            f"run_id: {record.run_id}",
            f"agent_id: {record.agent_id}",
            f"node_id: {record.node_id}",
            f"tool_name: {record.tool_name}",
            f"created_at: {record.created_at.isoformat()}",
        ]
        self.details.setPlainText("\n".join(lines))

    def _selected_approval_id(self) -> str | None:
        """Вернуть approval_id выбранной строки."""
        record = self._selected_record()
        if record is None:
            show_error(self, "Не выбрано подтверждение", "Выберите строку в таблице.")
            return None
        return record.approval_id

    def _selected_record(self) -> HumanApprovalRecord | None:
        """Вернуть выбранную запись подтверждения."""
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _show_result(self, run_id: str, status: str, errors: list[str]) -> None:
        """Показать итог продолжения запуска."""
        message = f"run_id: {run_id}\nСтатус запуска: {status}"
        if errors:
            message += "\nОшибки:\n" + "\n".join(errors)
        if any("SEND_DISABLED_FOR_SAFETY" in error for error in errors):
            message += (
                "\n\nДействие подтверждено, но отправка писем заблокирована "
                "безопасным режимом."
            )
        show_info(self, "Результат подтверждения", message)

