"""Страница «Мои задания»: история обращений к агентам с сервера."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.catalog.client import (
    CatalogClient,
    CatalogClientError,
    RunSummary,
)
from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.helpers import set_table_rows, show_error


class RunListWidget(QWidget):
    """Показывает сводки запусков текущего пользователя из Postgres."""

    HEADERS = [
        "run_id",
        "agent_id",
        "status",
        "title",
        "started_at",
        "finished_at",
    ]

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
        *,
        auth_session=None,
    ) -> None:
        """Создать страницу заданий."""
        super().__init__(parent)
        self._container = container
        self._auth_session = auth_session
        self._summaries: list[RunSummary] = []
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.show_runs)

        self.refresh_button = QPushButton("Обновить")
        self.auto_refresh_checkbox = QCheckBox("Автообновление")
        self.status_label = QLabel("")
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.details = QTextEdit()
        self.details.setReadOnly(True)

        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addWidget(self.auto_refresh_checkbox)
        top.addStretch(1)

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

        self.refresh_button.clicked.connect(self.show_runs)
        self.auto_refresh_checkbox.toggled.connect(self.set_auto_refresh)
        self.table.itemSelectionChanged.connect(self.show_selected_run_details)

    def set_auth_session(self, session) -> None:
        """Обновить сессию для API сводок."""
        self._auth_session = session

    def show_runs(self) -> None:
        """Показать историю обращений текущего пользователя."""
        session = self._auth_session
        if session is None or not session.proxy_url or not session.access_token:
            self._summaries = []
            set_table_rows(self.table, [], self.HEADERS)
            self.status_label.setText("Войдите в систему, чтобы увидеть задания.")
            self.details.clear()
            return
        try:
            self._summaries = CatalogClient.from_session(session).list_my_runs(
                session.access_token
            )
        except CatalogClientError as exc:
            self._summaries = []
            set_table_rows(self.table, [], self.HEADERS)
            self.status_label.setText(str(exc))
            self.details.clear()
            return
        except Exception as exc:
            self._summaries = []
            set_table_rows(self.table, [], self.HEADERS)
            self.status_label.setText(f"Ошибка загрузки заданий: {exc}")
            self.details.clear()
            return

        self.status_label.setText(
            "Обращений пока нет."
            if not self._summaries
            else f"Найдено обращений: {len(self._summaries)}"
        )
        rows = [
            [
                item.run_id,
                item.agent_id,
                item.status,
                item.title,
                item.started_at or "",
                item.finished_at or "",
            ]
            for item in self._summaries
        ]
        set_table_rows(self.table, rows, self.HEADERS)
        if self._summaries:
            self.table.selectRow(0)
        else:
            self.details.clear()

    def set_auto_refresh(self, enabled: bool) -> None:
        """Включить или выключить автообновление списка."""
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()

    def show_selected_run_details(self) -> None:
        """Показать карточку выбранного обращения."""
        item = self._selected_summary()
        if item is None:
            self.details.clear()
            return
        self.details.setPlainText(
            "\n".join(
                [
                    f"run_id: {item.run_id}",
                    f"agent_id: {item.agent_id}",
                    f"status: {item.status}",
                    f"title: {item.title}",
                    f"started_at: {item.started_at or '—'}",
                    f"finished_at: {item.finished_at or '—'}",
                    "",
                    "message:",
                    item.message or "—",
                ]
            )
        )

    def _selected_summary(self) -> RunSummary | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._summaries):
            return None
        return self._summaries[row]
