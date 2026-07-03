"""Каталог сохранённых агентов в виде карточек с запуском и историей."""

from __future__ import annotations

from threading import Event
from typing import Callable

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QFrame,
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
        self.title_label.setStyleSheet("font-size:16px; font-weight:700;")
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#9aa0aa;")

        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(2, 2, 8, 2)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch(1)

        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setWidget(self.cards_host)
        cards_scroll.setFrameShape(QFrame.Shape.NoFrame)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.title_label)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(cards_scroll)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._build_run_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

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
        actions = QHBoxLayout()
        actions.addWidget(self.run_button)
        actions.addWidget(self.stop_button)
        actions.addStretch(1)

        self.human_panel = HumanInteractionPanel()

        log_label = QLabel("Ход выполнения")
        log_label.setStyleSheet("font-weight:600; margin-top:6px;")
        self.live_log = QTextEdit()
        self.live_log.setReadOnly(True)
        self.live_log.setStyleSheet(
            "QTextEdit { background:#0f1116; color:#d6d9df; border:1px solid #2a2e37;"
            "border-radius:6px; font-family:Consolas,monospace; font-size:12px; }"
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
        """Перестроить список карточек агентов."""
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not self._agents:
            self.status_label.setText("Сохранённых агентов пока нет.")
            return
        self.status_label.setText(f"Агентов в каталоге: {len(self._agents)}")
        for agent in self._agents:
            self.cards_layout.insertWidget(
                self.cards_layout.count() - 1, self._build_card(agent)
            )

    def _build_card(self, agent: AgentSpec) -> QFrame:
        """Собрать карточку одного агента."""
        card = QFrame()
        card.setObjectName("agentCard")
        card.setStyleSheet(
            "#agentCard { background:#171a21; border:1px solid #2a2e37;"
            "border-radius:10px; }"
            "#agentCard:hover { border:1px solid #3d6fd6; }"
            "QLabel#cardTitle { font-size:14px; font-weight:700; color:#e8ebf0; }"
            "QLabel#cardDesc { color:#aab0ba; font-size:12px; }"
            "QLabel#cardMeta { color:#7f8794; font-size:11px; }"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 12, 12)
        row.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = QLabel(agent.name)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        desc = QLabel(agent.short_description or agent.description or agent.goal.main_goal)
        desc.setObjectName("cardDesc")
        desc.setWordWrap(True)
        meta = QLabel(self._format_created(agent.created_at))
        meta.setObjectName("cardMeta")
        info.addWidget(title)
        info.addWidget(desc)
        info.addWidget(meta)
        row.addLayout(info, 1)

        run_icon = QPushButton("▶")
        run_icon.setToolTip("Открыть и запустить агента")
        run_icon.setFixedSize(40, 40)
        run_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        run_icon.setStyleSheet(
            "QPushButton { background:#1f7a3d; color:#fff; border:none;"
            "border-radius:20px; font-size:16px; font-weight:700; }"
            "QPushButton:hover { background:#248c47; }"
        )
        run_icon.clicked.connect(lambda _=False, a=agent: self.open_agent(a))

        delete_icon = QPushButton("🗑")
        delete_icon.setToolTip("Удалить агента")
        delete_icon.setFixedSize(32, 32)
        delete_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_icon.setStyleSheet(
            "QPushButton { background:transparent; color:#c76b6b; border:none;"
            "font-size:15px; }"
            "QPushButton:hover { color:#e05656; }"
        )
        delete_icon.clicked.connect(lambda _=False, a=agent: self.delete_agent(a))

        right = QVBoxLayout()
        right.addWidget(run_icon, alignment=Qt.AlignmentFlag.AlignTop)
        right.addWidget(delete_icon, alignment=Qt.AlignmentFlag.AlignTop)
        right.addStretch(1)
        row.addLayout(right)
        return card

    @staticmethod
    def _format_created(created_at: str | None) -> str:
        """Отформатировать дату создания для карточки."""
        if not created_at:
            return "Дата создания: —"
        return f"Создан: {created_at[:16].replace('T', ' ')}"

    # ------------------------------------------------------- agent selection
    def open_agent(self, agent: AgentSpec) -> None:
        """Открыть правую панель агента: история запусков и запуск."""
        if self._is_busy():
            show_info(self, "Идёт выполнение", "Дождитесь завершения текущего запуска.")
            return
        self._selected_agent = agent
        self._paused_state = None
        self.human_panel.hide_panel()
        self.panel_title.setText(agent.name)
        self.panel_subtitle.setText(
            agent.short_description or agent.description or agent.goal.main_goal
        )
        self.run_button.setEnabled(True)
        self.live_log.clear()
        self.live_log.append(
            "Готов к запуску. Работа пойдёт по сохранённой схеме агента "
            "с актуальными данными."
        )
        self._load_history(agent.agent_id)

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
            self.live_log.clear()
            self.history_list.clear()
        self.refresh()

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
        """Кооперативно остановить выполняющегося агента."""
        if not self._is_busy():
            return
        self._cancel_event.set()
        self.stop_button.setEnabled(False)
        self.live_log.append("⏹ Запрошена остановка. Останавливаю после текущего шага…")

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
