"""Центральная зона планирования: запрос, уточнения, предварительный план."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.ui.widgets.composer_panel import (
    COMPOSER_PANEL_STYLESHEET,
    ComposerIconButton,
)
from agent_desktop_constructor.core.models.agent_spec import (
    AgentDataRequirement,
    AgentGraphNode,
    AgentSpec,
)

_BG = "#0B0B14"
_CARD = "#161625"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"
_OK = "#3dd68c"

_REQUEST_MIN_HEIGHT = 22
_REQUEST_MAX_HEIGHT = 120

_SOURCE_OPTIONS = (
    ("Электронная почта", "email"),
    ("Загруженный файл", "file"),
    ("Папка на диске", "folder"),
    ("Другое", "other"),
)


class _ComposerEdit(QTextEdit):
    """Поле ввода с Enter = отправка, Shift+Enter = новая строка."""

    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class PlanningCanvas(QWidget):
    """Холст этапа «Планирование» по референсу."""

    submit_requested = Signal(str)
    attach_requested = Signal()
    clear_attachments_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("planningCanvas")
        self._answers: dict[str, str] = {}
        self._attachment_paths: list[str] = []
        self._height_sync_pending = False
        self._resize_sync_timer = QTimer(self)
        self._resize_sync_timer.setSingleShot(True)
        self._resize_sync_timer.setInterval(48)
        self._resize_sync_timer.timeout.connect(self._apply_deferred_height_sync)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("planningBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._body_layout.setSpacing(14)

        self.request_bubble = QLabel("Опишите задачу в поле ниже и нажмите отправить.")
        self.request_bubble.setObjectName("requestBubble")
        self.request_bubble.setWordWrap(True)
        self._body_layout.addWidget(self.request_bubble)

        self.clarifications_title = QLabel("Уточним несколько деталей")
        self.clarifications_title.setObjectName("sectionTitle")
        self.clarifications_title.setVisible(False)
        self._body_layout.addWidget(self.clarifications_title)

        self.clarifications_host = QWidget()
        self.clarifications_layout = QVBoxLayout(self.clarifications_host)
        self.clarifications_layout.setContentsMargins(0, 0, 0, 0)
        self.clarifications_layout.setSpacing(10)
        self.clarifications_host.setVisible(False)
        self._body_layout.addWidget(self.clarifications_host)

        plan_header = QHBoxLayout()
        self.plan_title = QLabel("Предварительный план")
        self.plan_title.setObjectName("sectionTitle")
        self.plan_title.setVisible(False)
        self.ready_badge = QLabel("✓ Данных достаточно для построения workflow")
        self.ready_badge.setObjectName("readyBadge")
        self.ready_badge.setVisible(False)
        plan_header.addWidget(self.plan_title)
        plan_header.addStretch(1)
        plan_header.addWidget(self.ready_badge)
        self._body_layout.addLayout(plan_header)

        self.plan_host = QWidget()
        self.plan_layout = QVBoxLayout(self.plan_host)
        self.plan_layout.setContentsMargins(0, 0, 0, 0)
        self.plan_layout.setSpacing(6)
        self.plan_host.setVisible(False)
        self._body_layout.addWidget(self.plan_host)
        self._body_layout.addStretch(1)

        scroll.setWidget(body)

        self._composer_panel = self._build_bottom_composer()

        composer_host = QWidget()
        composer_host.setObjectName("composerHost")
        composer_layout = QVBoxLayout(composer_host)
        composer_layout.setContentsMargins(12, 18, 12, 12)
        composer_layout.setSpacing(0)
        composer_layout.addWidget(self._composer_panel)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(scroll, 1)
        root.addWidget(composer_host, 0)

        self.setStyleSheet(
            f"#planningCanvas, #planningBody {{ background: {_BG}; }}"
            f"#requestBubble {{ background: {_CARD}; color: {_TEXT}; border: 1px solid #2a2a3d;"
            "border-radius: 12px; padding: 14px 16px; font-size: 13px; }}"
            f"#sectionTitle {{ color: {_TEXT}; font-size: 14px; font-weight: 700; }}"
            f"#readyBadge {{ background: rgba(61,214,140,0.12); color: {_OK};"
            "border: 1px solid rgba(61,214,140,0.35); border-radius: 8px;"
            "padding: 6px 10px; font-size: 11px; font-weight: 600; }}"
            f"#clarifyCard {{ background: {_CARD}; border: 1px solid #2a2a3d;"
            "border-radius: 12px; }}"
            f"#clarifyQ {{ color: {_TEXT}; font-size: 12px; font-weight: 600; }}"
            f"#planStep {{ color: {_TEXT}; font-size: 12px; }}"
        )

    def _build_bottom_composer(self) -> QFrame:
        """Нижняя панель ввода в том же стиле, что на этапе тестирования."""
        composer = QFrame()
        composer.setObjectName("composerPanel")
        layout = QVBoxLayout(composer)
        layout.setContentsMargins(14, 10, 14, 13)
        layout.setSpacing(5)

        self.composer = _ComposerEdit()
        self.composer.setObjectName("requestEdit")
        self.composer.setPlaceholderText("Дополните задачу или задайте правило…")
        self.composer.setMinimumHeight(_REQUEST_MIN_HEIGHT)
        self.composer.setMaximumHeight(_REQUEST_MAX_HEIGHT)
        self.composer.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.composer.document().setDocumentMargin(0)
        self.composer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.composer.textChanged.connect(self._schedule_height_sync)
        self.composer.submit_requested.connect(self._emit_submit)
        self.composer.installEventFilter(self)
        layout.addWidget(self.composer)
        self._sync_composer_height()

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        attach_btn = ComposerIconButton("attach", "Прикрепить файл")
        attach_btn.clicked.connect(self.attach_requested.emit)
        toolbar.addWidget(attach_btn)
        toolbar.addWidget(ComposerIconButton("database", "Источники данных"))

        toolbar.addStretch(1)

        self._send_button = QPushButton("Отправить")
        self._send_button.setObjectName("composerSendButton")
        self._send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_button.setFixedHeight(28)
        self._send_button.clicked.connect(self._emit_submit)
        toolbar.addWidget(self._send_button)
        layout.addLayout(toolbar)

        attach_row = QHBoxLayout()
        attach_row.setContentsMargins(2, 0, 2, 0)
        attach_row.setSpacing(8)

        self.attachments_label = QLabel("")
        self.attachments_label.setObjectName("attachLabel")
        self.attachments_label.setWordWrap(True)
        self.attachments_label.setVisible(False)

        self._attach_clear_button = QPushButton("Очистить")
        self._attach_clear_button.setObjectName("attachClearButton")
        self._attach_clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_clear_button.setVisible(False)
        self._attach_clear_button.clicked.connect(self.clear_attachments_requested.emit)

        attach_row.addWidget(self.attachments_label, 1)
        attach_row.addWidget(self._attach_clear_button, 0)
        layout.addLayout(attach_row)

        composer.setStyleSheet(COMPOSER_PANEL_STYLESHEET)
        return composer

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.composer and event.type() == QEvent.Type.Resize:
            self._schedule_height_sync()
            return False
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_height_sync()

    def _schedule_height_sync(self) -> None:
        self._height_sync_pending = True
        self._resize_sync_timer.start()

    def _apply_deferred_height_sync(self) -> None:
        if not self._height_sync_pending:
            return
        self._height_sync_pending = False
        self._sync_composer_height()

    def _sync_composer_height(self) -> None:
        """Подстраивать высоту поля ввода под число строк, как на этапе тестирования."""
        edit = self.composer
        viewport_width = max(40, edit.viewport().width())
        document = edit.document()
        if abs(document.textWidth() - viewport_width) < 1.0 and edit.height() > 0:
            doc_height = document.size().height()
        else:
            document.setTextWidth(viewport_width)
            doc_height = document.size().height()
        frame = edit.frameWidth() * 2
        margins = edit.contentsMargins()
        target = int(doc_height + frame + margins.top() + margins.bottom() + 2)
        target = max(_REQUEST_MIN_HEIGHT, min(_REQUEST_MAX_HEIGHT, target))
        if edit.height() != target:
            edit.setFixedHeight(target)
        if target >= _REQUEST_MAX_HEIGHT:
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.verticalScrollBar().setValue(0)

    def request_text(self) -> str:
        """Текст в поле composer."""
        return self.composer.toPlainText().strip()

    def set_request_text(self, text: str) -> None:
        """Заполнить composer."""
        self.composer.setPlainText(text)
        self._sync_composer_height()

    def set_displayed_request(self, text: str) -> None:
        """Показать bubble с исходным запросом пользователя."""
        cleaned = (text or "").strip()
        self.request_bubble.setText(
            cleaned or "Опишите задачу в поле ниже и нажмите отправить."
        )

    def set_attachments(self, paths: list[str]) -> None:
        """Обновить список вложений под composer."""
        self._attachment_paths = list(paths)
        if not paths:
            self.attachments_label.clear()
            self.attachments_label.setVisible(False)
            self._attach_clear_button.setVisible(False)
            return
        names = ", ".join(Path(path).name for path in paths)
        self.attachments_label.setText(f"📎 {names}")
        self.attachments_label.setVisible(True)
        self._attach_clear_button.setVisible(True)

    def clarification_answers(self) -> dict[str, str]:
        """Выбранные ответы на уточнения (name → value)."""
        return dict(self._answers)

    def bind_preview(self, agent: AgentSpec | None) -> None:
        """Показать уточнения и план из AgentSpec после build_preview."""
        self._clear_layout(self.clarifications_layout)
        self._clear_layout(self.plan_layout)
        if agent is None:
            self.clarifications_title.setVisible(False)
            self.clarifications_host.setVisible(False)
            self.plan_title.setVisible(False)
            self.plan_host.setVisible(False)
            self.ready_badge.setVisible(False)
            return

        requirements = agent.data_requirements or []
        self.clarifications_title.setVisible(bool(requirements))
        self.clarifications_host.setVisible(bool(requirements))
        for req in requirements:
            self.clarifications_layout.addWidget(self._build_clarify_row(req))

        nodes = agent.graph_nodes or []
        self.plan_title.setVisible(bool(nodes))
        self.plan_host.setVisible(bool(nodes))
        self.ready_badge.setVisible(bool(nodes))
        for index, node in enumerate(nodes, start=1):
            step = QLabel(f"{index}. {node.title}")
            step.setObjectName("planStep")
            step.setWordWrap(True)
            self.plan_layout.addWidget(step)

    def _build_clarify_row(self, req: AgentDataRequirement) -> QWidget:
        card = QFrame()
        card.setObjectName("clarifyCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        question = QLabel(req.description or req.name)
        question.setObjectName("clarifyQ")
        question.setWordWrap(True)
        layout.addWidget(question)

        combo = QComboBox()
        for label, value in _SOURCE_OPTIONS:
            combo.addItem(label, value)
        current = (req.source_type or "").strip().lower()
        matched = False
        for i in range(combo.count()):
            if combo.itemData(i) == current or combo.itemText(i).casefold() == current:
                combo.setCurrentIndex(i)
                matched = True
                break
        if not matched and current:
            combo.addItem(req.source_type, current)
            combo.setCurrentIndex(combo.count() - 1)

        def on_changed(index: int, name: str = req.name) -> None:
            self._answers[name] = str(combo.itemData(index) or combo.currentText())

        combo.currentIndexChanged.connect(on_changed)
        self._answers[req.name] = str(combo.currentData() or combo.currentText())
        layout.addWidget(combo)

        if self._attachment_paths and current in {"file", "document", "documents"}:
            chip = QLabel(" · ".join(Path(p).name for p in self._attachment_paths[:3]))
            chip.setStyleSheet(
                f"color:{_MUTED}; font-size:11px; background:#0f0f1a;"
                "border-radius:8px; padding:4px 8px;"
            )
            layout.addWidget(chip)
        return card

    def _emit_submit(self) -> None:
        text = self.request_text()
        if text:
            self.submit_requested.emit(text)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


def plan_titles_from_nodes(nodes: list[AgentGraphNode]) -> list[str]:
    """Список заголовков узлов для тестов / внешних вызовов."""
    return [node.title for node in nodes]
