"""Каталог сохранённых агентов в виде карточек с запуском и историей."""

from __future__ import annotations

from threading import Event
from typing import Callable

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.helpers import (
    build_file_links_html,
    collect_produced_files,
    open_local_path,
    show_error,
    show_info,
)
from agent_desktop_constructor.app.ui.widgets.human_interaction_panel import (
    HumanInteractionPanel,
)
from agent_desktop_constructor.app.ui.workers.create_flow_worker import CreateFlowWorker
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)

_PAUSED_STATUSES = {
    AgentRunStatus.PAUSED_FOR_HUMAN,
    AgentRunStatus.PAUSED_FOR_CREDENTIALS,
}

GRID_COLUMNS = 3
MOCK_DESCRIPTION = "описание"


class DotCanvasWidget(QWidget):
    """Тёмный фон с точечной сеткой в стиле холста."""

    _DOT_TILE: QPixmap | None = None

    def __init__(self, parent: QWidget | None = None) -> None:
        """Создать холст с точками."""
        super().__init__(parent)
        self.setObjectName("dotCanvas")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        if DotCanvasWidget._DOT_TILE is None:
            DotCanvasWidget._DOT_TILE = self._build_dot_tile()

    @staticmethod
    def _build_dot_tile() -> QPixmap:
        """Создать повторяющуюся плитку с точкой."""
        spacing = 20
        tile = QPixmap(spacing, spacing)
        tile.fill(QColor("#0f1116"))
        with QPainter(tile) as painter:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#3a3f4b"))
            center = spacing // 2
            painter.drawEllipse(center - 1, center - 1, 2, 2)
        return tile

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Нарисовать тёмный фон и светлые точки."""
        if self.width() <= 0 or self.height() <= 0:
            return
        tile = DotCanvasWidget._DOT_TILE
        if tile is None:
            return
        with QPainter(self) as painter:
            painter.drawTiledPixmap(self.rect(), tile)
        super().paintEvent(event)


class AgentCard(QFrame):
    """Карточка агента в сетке."""

    def __init__(
        self,
        agent: AgentSpec,
        on_select: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        """Создать карточку агента."""
        super().__init__(parent)
        self.agent_id = agent.agent_id
        self._on_select = on_select
        self._selected = False
        self.setObjectName("agentCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(220, 268)

        self._image = QLabel("AI")
        self._image.setObjectName("agentCardImage")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setFixedHeight(120)

        self._name = QLabel(agent.name)
        self._name.setObjectName("agentCardName")
        self._name.setWordWrap(True)

        self._description = QLabel(MOCK_DESCRIPTION)
        self._description.setObjectName("agentCardDescription")
        self._description.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._image)
        layout.addWidget(self._name)
        layout.addWidget(self._description)
        layout.addStretch(1)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        """Подсветить выбранную карточку."""
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        border = "#4c8bf5" if self._selected else "#2b2f3a"
        bg = "#232733" if self._selected else "#1c1f27"
        self.setStyleSheet(
            f"#agentCard {{"
            f"background:{bg}; border:1px solid {border}; border-radius:14px;"
            f"}}"
            "#agentCardImage {"
            "background:qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #2f6bff, stop:1 #1c1f27);"
            "color:#ffffff; border-radius:10px; font-size:28px; font-weight:700;"
            "}"
            "#agentCardName { color:#f0f2f6; font-size:14px; font-weight:600; }"
            "#agentCardDescription { color:#8b909c; font-size:12px; }"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Выбрать агента по клику."""
        self._on_select(self.agent_id)
        super().mousePressEvent(event)


class AgentListWidget(QWidget):
    """Показывает сохранённых агентов карточками и позволяет запускать их."""

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать каталог агентов и сразу подгрузить список."""
        super().__init__(parent)
        self._container = container
        self._agents: list[AgentSpec] = []
        self._agent_cards: list[AgentCard] = []
        self._selected_agent: AgentSpec | None = None
        self._paused_state: AgentRuntimeState | None = None
        self._cancel_event = Event()
        self._thread: QThread | None = None
        self._worker: CreateFlowWorker | None = None

        self._build_ui()
        self._wire_signals()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        """Построить каркас: слева карточки, справа панель запуска/истории."""
        self.title_label = QLabel("Каталог агентов")
        self.title_label.setStyleSheet(
            "font-size:16px; font-weight:700; color:#e6e9ef;"
        )
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9aa0ac; font-size:12px;")

        self.cards_host = QWidget()
        self.cards_layout = QGridLayout(self.cards_host)
        self.cards_layout.setContentsMargins(16, 16, 16, 16)
        self.cards_layout.setHorizontalSpacing(16)
        self.cards_layout.setVerticalSpacing(16)
        self.cards_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self._canvas = DotCanvasWidget()
        canvas_layout = QVBoxLayout(self._canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)

        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setWidget(self.cards_host)
        cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        canvas_layout.addWidget(cards_scroll)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.title_label)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self._canvas, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._build_run_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setStyleSheet("background:#14161c; color:#e6e9ef;")

    def _build_run_panel(self) -> QWidget:
        """Правая панель: запуск выбранного агента и история его запусков."""
        self.panel_title = QLabel("Выберите агента слева")
        self.panel_title.setStyleSheet("font-size:15px; font-weight:700;")
        self.panel_subtitle = QLabel("")
        self.panel_subtitle.setWordWrap(True)
        self.panel_subtitle.setStyleSheet("color:#9aa0aa;")

        self.run_button = QPushButton("Запустить")
        self.run_button.setEnabled(False)
        self.stop_button = QPushButton("Остановить")
        self.stop_button.setEnabled(False)
        self.open_workspace_button = QPushButton("Открыть папку")
        self.open_workspace_button.setEnabled(False)
        self.delete_button = QPushButton("Удалить")
        self.delete_button.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(self.run_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.open_workspace_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)

        self.human_panel = HumanInteractionPanel()

        log_label = QLabel("Ход выполнения")
        log_label.setStyleSheet(
            "font-weight:700; margin-top:6px; color:#c7d2e5; font-size:12px;"
        )
        self.live_log = QTextEdit()
        self.live_log.setReadOnly(True)
        self.live_log.setStyleSheet(
            "QTextEdit {"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0b101a, stop:0.52 #0d1320, stop:1 #111827);"
            "color:#d8e0ee; border:1px solid #263247; border-radius:14px;"
            "padding:10px; font-family:Consolas,'Courier New',monospace;"
            "font-size:12px; selection-background-color:#2f6bff;"
            "}"
        )

        self.files_label = QLabel()
        self.files_label.setTextFormat(Qt.TextFormat.RichText)
        self.files_label.setOpenExternalLinks(False)
        self.files_label.setWordWrap(True)
        self.files_label.setVisible(False)
        self.files_label.setStyleSheet("color:#8ec3ff; font-size:12px; padding:4px 0;")
        self.files_label.linkActivated.connect(open_local_path)

        history_label = QLabel("История запусков")
        history_label.setStyleSheet("font-weight:600; margin-top:6px;")
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(160)

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(self.panel_title)
        panel_layout.addWidget(self.panel_subtitle)
        panel_layout.addLayout(actions)
        panel_layout.addWidget(self.human_panel)
        panel_layout.addWidget(log_label)
        panel_layout.addWidget(self.live_log, 1)
        panel_layout.addWidget(self.files_label)
        panel_layout.addWidget(history_label)
        panel_layout.addWidget(self.history_list)
        return panel

    def _wire_signals(self) -> None:
        """Подключить обработчики кнопок и панели человека."""
        self.run_button.clicked.connect(self.run_current_agent)
        self.stop_button.clicked.connect(self.request_stop)
        self.open_workspace_button.clicked.connect(self.open_selected_agent_workspace)
        self.delete_button.clicked.connect(self.delete_current_agent)
        self.human_panel.continue_requested.connect(self.continue_after_human)
        self.history_list.itemSelectionChanged.connect(self._show_selected_run_events)

    # -------------------------------------------------------------- loading
    def refresh(self) -> None:
        """Подгрузить агентов и перерисовать карточки."""
        try:
            self._agents = self._container.agent_service.list_agents()
        except Exception as exc:
            show_error(self, "Ошибка загрузки агентов", exc)
            return
        self._render_cards()

    def _render_cards(self) -> None:
        """Перестроить сетку карточек агентов."""
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._agent_cards.clear()

        if not self._agents:
            self.status_label.setText("Сохранённых агентов пока нет.")
            return
        self.status_label.setText(f"Агентов в каталоге: {len(self._agents)}")
        selected_id = (
            self._selected_agent.agent_id if self._selected_agent is not None else None
        )
        for index, agent in enumerate(self._agents):
            card = AgentCard(agent, self._on_card_selected)
            card.set_selected(agent.agent_id == selected_id)
            row = index // GRID_COLUMNS
            column = index % GRID_COLUMNS
            self.cards_layout.addWidget(card, row, column, Qt.AlignmentFlag.AlignTop)
            self._agent_cards.append(card)
        self.cards_host.adjustSize()

    def _on_card_selected(self, agent_id: str) -> None:
        """Открыть агента при выборе карточки."""
        for agent in self._agents:
            if agent.agent_id == agent_id:
                self.open_agent(agent)
                return

    def _highlight_card(self, agent_id: str | None) -> None:
        """Подсветить выбранную карточку в сетке."""
        for card in self._agent_cards:
            card.set_selected(card.agent_id == agent_id)

    # ------------------------------------------------------- agent selection
    def open_agent(self, agent: AgentSpec) -> None:
        """Открыть правую панель агента: история запусков и запуск."""
        if self._is_busy():
            show_info(self, "Идёт выполнение", "Дождитесь завершения текущего запуска.")
            return
        self._selected_agent = agent
        self._highlight_card(agent.agent_id)
        self._paused_state = None
        self.human_panel.hide_panel()
        self.panel_title.setText(agent.name)
        self.panel_subtitle.setText(
            agent.short_description or agent.description or agent.goal.main_goal
        )
        self.run_button.setEnabled(True)
        self.open_workspace_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.live_log.clear()
        self.live_log.append(
            "Готов к запуску. Работа пойдёт по сохранённой схеме агента "
            "с актуальными данными."
        )
        self._load_history(agent.agent_id)

    def delete_current_agent(self) -> None:
        """Удалить выбранного агента."""
        if self._selected_agent is None:
            show_error(self, "Агент не выбран", "Откройте карточку агента.")
            return
        self.delete_agent(self._selected_agent)

    def delete_agent(self, agent: AgentSpec) -> None:
        """Удалить агента из каталога."""
        if self._is_busy():
            show_info(self, "Идёт выполнение", "Дождитесь завершения запуска.")
            return
        try:
            self._container.agent_service.delete_agent(agent.agent_id)
        except Exception as exc:
            show_error(self, "Ошибка удаления", exc)
            return
        if self._selected_agent is not None and (
            self._selected_agent.agent_id == agent.agent_id
        ):
            self._selected_agent = None
            self.panel_title.setText("Выберите агента слева")
            self.panel_subtitle.clear()
            self.run_button.setEnabled(False)
            self.open_workspace_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.live_log.clear()
            self.history_list.clear()
            self._highlight_card(None)
        self.refresh()

    def open_selected_agent_workspace(self) -> None:
        """Открыть папку документов выбранного агента."""
        if self._selected_agent is None:
            show_info(self, "Агент не выбран", "Сначала выберите агента.")
            return
        service = self._container.agent_service
        if not hasattr(service, "agent_workspace_dir"):
            show_error(self, "Папка недоступна", "Сервис не поддерживает workspace агента.")
            return
        folder = service.agent_workspace_dir(self._selected_agent.agent_id)
        if not folder:
            show_error(self, "Папка недоступна", "Не удалось определить папку агента.")
            return
        open_local_path(folder)

    # ------------------------------------------------------------- history
    def _load_history(self, agent_id: str) -> None:
        """Показать список прошлых запусков агента."""
        self.history_list.clear()
        try:
            runs = self._container.agent_service.list_runs(agent_id)
        except Exception:
            item = QListWidgetItem("История запусков недоступна (нет хранилища).")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.history_list.addItem(item)
            return
        if not runs:
            item = QListWidgetItem("Запусков пока нет.")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.history_list.addItem(item)
            return
        for run in reversed(runs):
            label = f"{run.status.value} · {run.run_id[:8]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, run.run_id)
            self.history_list.addItem(item)

    def _show_selected_run_events(self) -> None:
        """Показать журнал событий выбранного из истории запуска."""
        items = self.history_list.selectedItems()
        if not items:
            return
        run_id = items[0].data(Qt.ItemDataRole.UserRole)
        if not run_id:
            return
        try:
            events = self._container.agent_service.list_run_events(run_id)
        except Exception as exc:
            show_error(self, "Ошибка загрузки событий", exc)
            return
        self.live_log.clear()
        self.live_log.append(f"История запуска {run_id[:8]}:")
        for event in events:
            self.live_log.append(f"• {event.message}")

    # --------------------------------------------------------------- run
    def run_current_agent(self) -> None:
        """Запустить выбранного агента по его сохранённой схеме с live-логом."""
        agent = self._selected_agent
        if agent is None:
            show_error(self, "Агент не выбран", "Откройте карточку агента.")
            return
        if self._is_busy():
            return
        self._paused_state = None
        self.human_panel.hide_panel()
        self.files_label.setVisible(False)
        self._cancel_event.clear()
        self.live_log.clear()
        self.live_log.append(f"▶ Запуск агента «{agent.name}»…")

        service = self._container.agent_service
        cancel_event = self._cancel_event
        agent_id = agent.agent_id

        def job(progress: Callable[[str], None]) -> object:
            return service.run_saved_agent(
                agent_id,
                progress_callback=progress,
                cancel_callback=cancel_event.is_set,
            )

        self._run_in_background(job, self._on_run_completed, self._on_run_failed)

    def continue_after_human(self, answer: str) -> None:
        """Продолжить приостановленный запуск после ответа/действия человека."""
        agent = self._selected_agent
        state = self._paused_state
        if agent is None or state is None or self._is_busy():
            return
        self.human_panel.hide_panel()
        self._cancel_event.clear()
        self.live_log.append(f"▶ Продолжаю после ответа человека: {answer}")

        service = self._container.agent_service
        cancel_event = self._cancel_event

        def job(progress: Callable[[str], None]) -> object:
            return service.resume_saved_agent_after_human(
                agent,
                state,
                answer,
                approved=True,
                progress_callback=progress,
                cancel_callback=cancel_event.is_set,
            )

        self._run_in_background(job, self._on_run_completed, self._on_run_failed)

    def _on_run_completed(self, state: object) -> None:
        """Обработать результат запуска: пауза для человека или завершение."""
        if not isinstance(state, AgentRuntimeState):
            return
        if state.status in _PAUSED_STATUSES:
            self._prompt_human(state)
            return
        self._paused_state = None
        final_message = state.variables.get("final_message")
        if final_message:
            self.live_log.append(f"✅ Итог: {final_message}")
        self.live_log.append(
            f"Готово. Статус: {state.status.value}, run_id={state.run_id[:8]}."
        )
        if state.errors:
            self.live_log.append("Ошибки:\n" + "\n".join(state.errors))
        self._show_produced_files(state)
        if self._selected_agent is not None:
            self._load_history(self._selected_agent.agent_id)

    def _show_produced_files(self, state: AgentRuntimeState) -> None:
        """Показать ссылки на файлы, созданные агентом, и на его папку."""
        files = collect_produced_files(state)
        folder = None
        service = self._container.agent_service
        if self._selected_agent is not None and hasattr(service, "agent_workspace_dir"):
            folder = service.agent_workspace_dir(self._selected_agent.agent_id)
        html = build_file_links_html(files, folder)
        if html:
            self.files_label.setText(html)
            self.files_label.setVisible(True)
        else:
            self.files_label.setVisible(False)

    def _prompt_human(self, state: AgentRuntimeState) -> None:
        """Показать панель участия человека по приостановленному состоянию."""
        self._paused_state = state
        approval = state.pending_human_approval
        variables = state.variables or {}
        if approval is not None:
            question = approval.question
            options = list(approval.options)
        else:
            question = variables.get(
                "credential_request_reason", "Агенту требуется ваше участие."
            )
            options = ["Я выполнил(а) требуемое действие"]
        self.live_log.append("⏸ Агент ожидает вашего ответа/действия.")
        self.human_panel.prompt(question, options, variables.get("human_plan_ahead"))

    def _on_run_failed(self, message: str) -> None:
        """Показать ошибку запуска."""
        self._paused_state = None
        self.live_log.append(f"⚠ Ошибка запуска: {message}")
        show_error(self, "Ошибка запуска агента", message)

    # ------------------------------------------------------- background flow
    def _is_busy(self) -> bool:
        """Вернуть True, если фоновый запуск ещё идёт."""
        return self._thread is not None

    def request_stop(self) -> None:
        """Остановить агента: прерывает ожидание ответа LLM и шаги цикла."""
        if not self._is_busy():
            return
        self._cancel_event.set()
        self.stop_button.setEnabled(False)
        self.live_log.append(
            "⏹ Запрошена остановка. Прерываю текущий запрос к модели…"
        )

    def _append_log(self, message: str) -> None:
        """Добавить строку в живой лог."""
        self.live_log.append(message)
        scrollbar = self.live_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _run_in_background(
        self,
        job: Callable[[Callable[[str], None]], object],
        on_completed: Callable[[object], None],
        on_failed: Callable[[str], None],
    ) -> None:
        """Запустить job в QThread, транслируя прогресс в живой лог."""
        if self._is_busy():
            return
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        thread = QThread()
        worker = CreateFlowWorker(job)
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._append_log)
        worker.completed.connect(on_completed)
        worker.failed.connect(on_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_background_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_background_finished(self) -> None:
        """Сбросить ссылки на поток и вернуть кнопки в активное состояние."""
        thread = self._thread
        if thread is not None:
            thread.wait(5000)
        self._thread = None
        self._worker = None
        self.stop_button.setEnabled(False)
        self._cancel_event.clear()
        self.run_button.setEnabled(self._selected_agent is not None)
