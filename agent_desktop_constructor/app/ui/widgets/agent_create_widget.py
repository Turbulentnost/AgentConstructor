"""Страница создания агента в стиле пошагового workflow (Cursor/Codex).

UI-слой не меняет внутреннюю логику конструктора: используются те же вызовы
``agent_service`` (build_preview / validate_agent / create_validate_and_run_once /
save_agent / create_agent_from_request). Экран лишь показывает наглядно, что агент
построил, что проверяет, что запускает и почему что-то не сработало.
"""

from __future__ import annotations

from threading import Event
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.bootstrap import ApplicationContainer
from agent_desktop_constructor.app.ui.helpers import (
    build_file_links_html,
    collect_produced_files,
    format_json_preview,
    open_local_path,
    set_table_rows,
    show_error,
    show_info,
)
from agent_desktop_constructor.app.ui.workers.create_flow_worker import CreateFlowWorker
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus

EXAMPLE_REQUEST = (
    "Собери мои поручения из почты Outlook и из 1С "
    "и подготовь отчёт с рисками просрочки"
)

# Порядок стадий пошаговой ленты выполнения.
STAGE_REQUEST = "request"
STAGE_PLAN = "plan"
STAGE_TOOLS = "tools"
STAGE_GRAPH = "graph"
STAGE_CHECK = "check"
STAGE_TRIAL = "trial"
STAGE_QUALITY = "quality"
STAGE_RESULT = "result"
STAGE_DEV = "dev"

STAGE_ORDER: list[tuple[str, str, str]] = [
    (STAGE_REQUEST, "Запрос пользователя", "Что попросил пользователь"),
    (STAGE_PLAN, "План LLM", "Как LLM поняла задачу"),
    (STAGE_TOOLS, "Выбранные инструменты", "Какие инструменты выбраны"),
    (STAGE_GRAPH, "Граф выполнения", "Порядок шагов агента"),
    (STAGE_CHECK, "Проверка инструментов", "Регистрация и доступность"),
    (STAGE_TRIAL, "Пробный запуск", "Выполнение агента"),
    (STAGE_QUALITY, "Оценка качества результатов", "Достаточно ли данных"),
    (STAGE_RESULT, "Итог проверки", "Общий вывод"),
    (STAGE_DEV, "JSON для разработчика", "Технические детали"),
]

# status -> (подпись бейджа, цвет фона, цвет текста, значок)
STATUS_STYLE: dict[str, tuple[str, str, str, str]] = {
    "pending": ("Ожидает", "#20283a", "#9da9bf", "○"),
    "running": ("В процессе", "#183a76", "#dbe8ff", "◐"),
    "passed": ("Готово", "#113d2a", "#c9ffdf", "✓"),
    "warning": ("Внимание", "#4c3d19", "#ffe7a3", "!"),
    "failed": ("Ошибка", "#551f2c", "#ffd4df", "✕"),
    "needs_human": ("Нужен человек", "#57351c", "#ffe1bd", "☺"),
    "needs_credentials": ("Авторизация", "#4c3d19", "#ffe7a3", "🔑"),
}


def _short(text: object, max_len: int = 90) -> str:
    """Короткая однострочная подпись для карточки."""
    value = " ".join(str(text or "").split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


class NeonStepIndicator(QWidget):
    """Неоновый индикатор шага: круг, галочка и линия перехода."""

    def __init__(
        self,
        index: int,
        is_last: bool,
        parent: QWidget | None = None,
    ) -> None:
        """Создать индикатор с анимируемыми progress-свойствами."""
        super().__init__(parent)
        self._index = index
        self._is_last = is_last
        self._status = "pending"
        self._outline_progress = 0.0
        self._check_progress = 0.0
        self._connector_progress = 0.0
        self._dash_offset = 0.0
        self._pulse = 0.0
        self._animations: list[QPropertyAnimation] = []

        self.setFixedWidth(48)
        self.setMinimumHeight(80)

        self._motion_timer = QTimer(self)
        self._motion_timer.setInterval(28)
        self._motion_timer.timeout.connect(self._advance_motion)

    def _advance_motion(self) -> None:
        """Обновить dash-offset и пульсацию для running-состояния."""
        self._dash_offset = (self._dash_offset + 0.9) % 32
        self._pulse = (self._pulse + 0.035) % 1.0
        if self._status == "running":
            self._outline_progress = 0.18 + (self._pulse * 0.72)
        self.update()

    def set_status(self, status: str) -> None:
        """Запустить визуальную анимацию под новый статус."""
        self._status = status
        self._clear_animations()
        if status == "running":
            self._check_progress = 0.0
            self._motion_timer.start()
        elif status == "passed":
            self._motion_timer.stop()
            self._animate_to("outlineProgress", self._outline_progress, 1.0, 760)
            self._animate_to("connectorProgress", self._connector_progress, 1.0, 680)
            self._animate_to("checkProgress", 0.0, 1.0, 980, delay_ms=360)
        elif status in {"failed", "warning", "needs_human", "needs_credentials"}:
            self._motion_timer.stop()
            self._outline_progress = 1.0
            self._connector_progress = 0.0
            self._check_progress = 0.0
        else:
            self._motion_timer.stop()
            self._outline_progress = 0.0
            self._connector_progress = 0.0
            self._check_progress = 0.0
        self.update()

    def _animate_to(
        self,
        property_name: bytes | str,
        start: float,
        end: float,
        duration_ms: int,
        delay_ms: int = 0,
    ) -> None:
        """Анимировать одно числовое свойство индикатора."""
        property_bytes = (
            bytes(property_name, "ascii")
            if isinstance(property_name, str)
            else property_name
        )
        animation = QPropertyAnimation(self, property_bytes)
        animation.setDuration(duration_ms)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def start_animation() -> None:
            animation.start()

        animation.finished.connect(
            lambda: (
                self._animations.remove(animation)
                if animation in self._animations
                else None
            )
        )
        self._animations.append(animation)
        if delay_ms:
            QTimer.singleShot(delay_ms, start_animation)
        else:
            start_animation()

    def _clear_animations(self) -> None:
        for animation in list(self._animations):
            animation.stop()
        self._animations.clear()

    def _status_color(self) -> QColor:
        if self._status == "passed":
            return QColor("#2fffa3")
        if self._status == "running":
            return QColor("#4b8bff")
        if self._status == "failed":
            return QColor("#ff5d7a")
        if self._status in {"warning", "needs_human", "needs_credentials"}:
            return QColor("#ffd166")
        return QColor("#52607a")

    def _glow_pen(self, color: QColor, width: float, alpha: int) -> QPen:
        glow = QColor(color)
        glow.setAlpha(alpha)
        pen = QPen(glow, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Нарисовать круг, анимированную обводку, галочку и connector."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(24, 27)
        radius = 14
        circle_rect = QRectF(
            center.x() - radius,
            center.y() - radius,
            radius * 2,
            radius * 2,
        )
        color = self._status_color()

        if not self._is_last:
            self._paint_connector(painter, center, radius, color)

        # Base dashed neon circle.
        base = QColor("#637391")
        base.setAlpha(112)
        base_pen = QPen(base, 1.15)
        base_pen.setDashPattern([3.5, 5.5])
        base_pen.setDashOffset(self._dash_offset)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(base_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle_rect)

        if self._status == "pending":
            painter.setPen(QColor("#8291ad"))
            painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, str(self._index))
            return

        # Soft glow behind active arc.
        for width, alpha in ((10, 20), (5.5, 42), (2.6, 190)):
            painter.setPen(self._glow_pen(color, width, alpha))
            painter.drawArc(
                circle_rect,
                90 * 16,
                int(-360 * 16 * max(0.03, min(1.0, self._outline_progress))),
            )

        if self._status == "passed":
            painter.setPen(QColor("#0b1713"))
            painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, "")
            self._paint_check(painter, center, color)
        elif self._status == "running":
            dot = QColor("#eef5ff")
            painter.setPen(QPen(dot, 1.0))
            painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, str(self._index))
        elif self._status == "failed":
            painter.setPen(self._glow_pen(color, 2.5, 230))
            painter.drawLine(QPointF(19, 22), QPointF(29, 32))
            painter.drawLine(QPointF(29, 22), QPointF(19, 32))
        else:
            painter.setPen(self._glow_pen(color, 2.6, 230))
            painter.drawLine(QPointF(24, 19), QPointF(24, 29))
            painter.drawPoint(QPointF(24, 35))

    def _paint_connector(
        self,
        painter: QPainter,
        center: QPointF,
        radius: int,
        color: QColor,
    ) -> None:
        start_y = center.y() + radius + 7
        end_y = self.height() - 6
        x = center.x()
        if end_y <= start_y:
            return

        pending = QColor("#354052")
        pending.setAlpha(130)
        pending_pen = QPen(pending, 1.2)
        pending_pen.setDashPattern([3.5, 5.5])
        pending_pen.setDashOffset(self._dash_offset)
        pending_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pending_pen)
        painter.drawLine(QPointF(x, start_y), QPointF(x, end_y))

        progress = max(0.0, min(1.0, self._connector_progress))
        if progress <= 0:
            return
        solid_end = start_y + (end_y - start_y) * progress
        for width, alpha in ((6, 22), (3, 74), (1.6, 220)):
            painter.setPen(self._glow_pen(color, width, alpha))
            painter.drawLine(QPointF(x, start_y), QPointF(x, solid_end))

    def _paint_check(self, painter: QPainter, center: QPointF, color: QColor) -> None:
        progress = max(0.0, min(1.0, self._check_progress))
        if progress <= 0:
            return

        start = QPointF(center.x() - 6, center.y())
        mid = QPointF(center.x() - 2, center.y() + 5)
        end = QPointF(center.x() + 9, center.y() - 7)

        path = QPainterPath(start)
        if progress <= 0.42:
            local = progress / 0.42
            point = QPointF(
                start.x() + (mid.x() - start.x()) * local,
                start.y() + (mid.y() - start.y()) * local,
            )
            path.lineTo(point)
        else:
            path.lineTo(mid)
            local = (progress - 0.42) / 0.58
            point = QPointF(
                mid.x() + (end.x() - mid.x()) * local,
                mid.y() + (end.y() - mid.y()) * local,
            )
            path.lineTo(point)

        for width, alpha in ((7, 28), (4, 82), (2.4, 245)):
            painter.setPen(self._glow_pen(color, width, alpha))
            painter.drawPath(path)

    def get_outline_progress(self) -> float:
        return self._outline_progress

    def set_outline_progress(self, value: float) -> None:
        self._outline_progress = float(value)
        self.update()

    def get_check_progress(self) -> float:
        return self._check_progress

    def set_check_progress(self, value: float) -> None:
        self._check_progress = float(value)
        self.update()

    def get_connector_progress(self) -> float:
        return self._connector_progress

    def set_connector_progress(self, value: float) -> None:
        self._connector_progress = float(value)
        self.update()

    outlineProgress = Property(
        float,
        get_outline_progress,
        set_outline_progress,
    )
    checkProgress = Property(float, get_check_progress, set_check_progress)
    connectorProgress = Property(
        float,
        get_connector_progress,
        set_connector_progress,
    )


class StageCard(QFrame):
    """Карточка одной стадии в неоновой ленте выполнения."""

    def __init__(
        self,
        index: int,
        stage_id: str,
        title: str,
        subtitle: str,
        is_last: bool,
        on_click: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        """Создать карточку стадии."""
        super().__init__(parent)
        self.stage_id = stage_id
        self._on_click = on_click
        self._status = "pending"
        self._selected = False
        self.setObjectName("stageCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)

        self._indicator = NeonStepIndicator(index, is_last)

        self._title = QLabel(title)
        self._title.setObjectName("stageTitle")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("stageSubtitle")
        self._subtitle.setWordWrap(True)

        self._badge = QLabel()
        self._badge.setObjectName("stageBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._indicator, 0, Qt.AlignmentFlag.AlignTop)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 8, 12, 8)
        text_col.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)
        text_col.addLayout(title_row)
        text_col.addWidget(self._subtitle)
        text_col.addStretch(1)
        row.addLayout(text_col, 1)

        self.set_status("pending")

    def set_status(self, status: str) -> None:
        """Обновить статус стадии и перерисовать бейдж."""
        self._status = status if status in STATUS_STYLE else "pending"
        label, bg, fg, icon = STATUS_STYLE[self._status]
        self._indicator.set_status(self._status)
        self._badge.setText(f"{icon} {label}")
        self._badge.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:9px;"
            "padding:3px 10px; font-size:11px; font-weight:600;"
        )
        self._apply_frame_style()

    def set_subtitle(self, subtitle: str) -> None:
        """Обновить подпись стадии."""
        self._subtitle.setText(subtitle)

    def set_selected(self, selected: bool) -> None:
        """Подсветить выбранную карточку."""
        self._selected = selected
        self._apply_frame_style()

    def _apply_frame_style(self) -> None:
        border = "#5d8cff" if self._selected else "#243047"
        bg = "#192030" if self._selected else "#111722"
        glow = "rgba(77,139,255,0.22)" if self._selected else "rgba(47,255,163,0.08)"
        self.setStyleSheet(
            "#stageCard {"
            f"background:{bg}; border:1px solid {border};"
            "border-radius:14px;"
            "}"
            "#stageCard:hover { border:1px solid #536b99; background:#151d2b; }"
            f"#stageCard {{ selection-background-color:{glow}; }}"
            "#stageTitle { color:#f5f7ff; font-size:13px; font-weight:700; }"
            "#stageSubtitle { color:#8d9ab3; font-size:11px; line-height:1.35; }"
            "#stageBadge { border:1px solid rgba(255,255,255,0.07); }"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Выбрать стадию по клику."""
        self._on_click(self.stage_id)
        super().mousePressEvent(event)


class LiveLogView(QScrollArea):
    """Стеклянная лента live-событий вместо обычного текстового поля."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Создать прокручиваемую ленту событий агента."""
        super().__init__(parent)
        self._items: list[QFrame] = []
        self._animations: list[QPropertyAnimation] = []

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("liveLogView")

        self._host = QWidget()
        self._host.setObjectName("liveLogHost")
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(7)

        self._placeholder = QLabel(
            "События появятся здесь: LLM-планирование, вызовы инструментов, "
            "проверки, ожидание человека и итог."
        )
        self._placeholder.setWordWrap(True)
        self._placeholder.setObjectName("livePlaceholder")
        self._layout.addWidget(self._placeholder)
        self._layout.addStretch(1)

        self.setWidget(self._host)
        self.setStyleSheet(
            "#liveLogView {"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0b101a, stop:0.52 #0d1320, stop:1 #111827);"
            "border:1px solid #263247; border-radius:14px;"
            "}"
            "#liveLogHost { background:transparent; }"
            "#livePlaceholder { color:#66738b; font-size:12px; padding:8px; }"
            "#liveLogItem {"
            "background:rgba(18,26,41,0.82); border:1px solid #253249;"
            "border-radius:10px;"
            "}"
            "#liveLogItem QLabel { color:#d6deec; font-size:12px; }"
            "#liveLogMeta { color:#7e8ba5; font-size:10px; font-weight:700; }"
            "#liveLogDot { border-radius:5px; }"
        )

    def setReadOnly(self, _read_only: bool) -> None:  # noqa: N802 (Qt compatibility)
        """Совместимость с QTextEdit API."""

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 (Qt compatibility)
        """Совместимость с QTextEdit API."""
        self._placeholder.setText(text)

    def append(self, message: str) -> None:
        """Добавить событие в ленту с мягким появлением."""
        text = str(message or "").strip()
        if not text:
            return
        self._placeholder.setVisible(False)

        item = QFrame()
        item.setObjectName("liveLogItem")
        item.setStyleSheet(self._item_style(text))

        dot = QLabel()
        dot.setObjectName("liveLogDot")
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background:{self._accent_color(text)}; border-radius:5px;")

        meta = QLabel(self._event_label(text))
        meta.setObjectName("liveLogMeta")

        body = QLabel(self._clean_message(text))
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(7)
        header.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(meta, 1)

        layout = QVBoxLayout(item)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        layout.addLayout(header)
        layout.addWidget(body)

        self._layout.insertWidget(max(0, self._layout.count() - 1), item)
        self._items.append(item)
        if len(self._items) > 80:
            old = self._items.pop(0)
            old.setParent(None)
            old.deleteLater()
        self._fade_in(item)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def clear(self) -> None:
        """Очистить события."""
        for item in self._items:
            item.setParent(None)
            item.deleteLater()
        self._items.clear()
        self._placeholder.setVisible(True)

    def _fade_in(self, item: QWidget) -> None:
        effect = QGraphicsOpacityEffect(item)
        effect.setOpacity(0.0)
        item.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(260)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(
            lambda: (
                self._animations.remove(animation)
                if animation in self._animations
                else None
            )
        )
        self._animations.append(animation)
        animation.start()

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _event_label(self, text: str) -> str:
        if text.startswith("✅"):
            return "COMPLETED"
        if text.startswith("⚠") or text.startswith("❌"):
            return "ATTENTION"
        if text.startswith("⏸"):
            return "WAITING FOR HUMAN"
        if text.startswith("📎"):
            return "ATTACHMENT"
        if text.startswith("🧩") or "LLM" in text:
            return "LLM"
        if text.startswith("🔎"):
            return "CHECK"
        if text.startswith("▶"):
            return "RUN"
        if text.startswith("⏹"):
            return "STOP"
        return "EVENT"

    def _accent_color(self, text: str) -> str:
        if text.startswith("✅"):
            return "#2fffa3"
        if text.startswith("⚠") or text.startswith("❌"):
            return "#ff5d7a"
        if text.startswith("⏸"):
            return "#ffd166"
        if text.startswith("📎"):
            return "#8ec3ff"
        if text.startswith("🔎"):
            return "#c084fc"
        if text.startswith("▶"):
            return "#4b8bff"
        return "#7aa2ff"

    def _item_style(self, text: str) -> str:
        color = self._accent_color(text)
        return (
            "#liveLogItem {"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {color}, stop:0.012 #172033, stop:1 #0f1624);"
            f"border:1px solid {color}; border-radius:10px;"
            "}"
        )

    @staticmethod
    def _clean_message(text: str) -> str:
        return text.lstrip("✅⚠❌⏸📎🧩🔎▶⏹ ").strip() or text


class AgentCreateWidget(QWidget):
    """Пошаговый экран создания и проверки агента.

    Внутренняя логика конструктора не меняется — виджет только визуализирует
    результаты вызовов ``agent_service``.
    """

    def __init__(
        self,
        container: ApplicationContainer,
        parent: QWidget | None = None,
    ) -> None:
        """Создать страницу создания агента."""
        super().__init__(parent)
        self._container = container
        self._preview_agent: AgentSpec | None = None
        self._last_request: str = ""
        self._stage_cards: dict[str, StageCard] = {}
        self._stage_details: dict[str, str] = {}
        self._selected_stage: str | None = None
        self._thread: QThread | None = None
        self._worker: CreateFlowWorker | None = None
        self._action_buttons: list[QPushButton] = []
        self._cancel_event = Event()
        self._paused_agent: AgentSpec | None = None
        self._paused_state: object | None = None
        self._human_radios: list[tuple[QRadioButton, str | None]] = []
        self._attachment_paths: list[str] = []

        self._build_ui()
        self._connect_signals()
        self._reset_stages()
        self.select_stage(STAGE_REQUEST)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        """Собрать трёхзонную компоновку: центр + правая панель деталей."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_details_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

    def _build_center(self) -> QWidget:
        """Центральная рабочая область: заголовок, запрос, кнопки, лента."""
        container = QWidget()
        container.setObjectName("centerArea")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Создать агента")
        title.setObjectName("screenTitle")
        title.setStyleSheet("font-size:21px; font-weight:800; color:#f6f8ff;")
        layout.addWidget(title)

        request_label = QLabel("Запрос пользователя")
        request_label.setStyleSheet("color:#9aa0ac; font-size:12px;")
        layout.addWidget(request_label)

        self.request_edit = QTextEdit()
        self.request_edit.setPlaceholderText(EXAMPLE_REQUEST)
        self.request_edit.setFixedHeight(96)
        self.request_edit.setStyleSheet(
            "background:#0f1624; color:#e8eefb; border:1px solid #263247;"
            "border-radius:12px; padding:10px; font-size:13px;"
            "selection-background-color:#2f6bff;"
        )
        layout.addWidget(self.request_edit)

        attach_row = QHBoxLayout()
        self.attach_button = QPushButton("📎 Прикрепить файл")
        self.attach_button.setStyleSheet(
            "QPushButton { background:#232733; color:#e6e9ef; border:1px solid #333846;"
            "border-radius:8px; padding:7px 12px; font-size:12px; }"
            "QPushButton:hover { border:1px solid #3d6fd6; }"
        )
        self.attach_button.clicked.connect(self.attach_files)
        self.attach_clear_button = QPushButton("Очистить вложения")
        self.attach_clear_button.setStyleSheet(
            "QPushButton { background:transparent; color:#9aa0ac; border:none;"
            "font-size:11px; }"
            "QPushButton:hover { color:#c76b6b; }"
        )
        self.attach_clear_button.clicked.connect(self.clear_attachments)
        self.attach_label = QLabel("Файлы не прикреплены")
        self.attach_label.setStyleSheet("color:#7f8794; font-size:11px;")
        attach_row.addWidget(self.attach_button)
        attach_row.addWidget(self.attach_clear_button)
        attach_row.addWidget(self.attach_label, 1)
        layout.addLayout(attach_row)

        layout.addLayout(self._build_buttons())

        self._human_panel = self._build_human_panel()
        self._human_panel.setVisible(False)
        layout.addWidget(self._human_panel)

        # Живой ход выполнения: показывает текст LLM и вызовы инструментов в
        # реальном времени, чтобы окно не выглядело зависшим.
        live_label = QLabel("Живой ход выполнения")
        live_label.setStyleSheet(
            "color:#c7d2e5; font-size:12px; font-weight:700; "
            "letter-spacing:0.4px;"
        )
        layout.addWidget(live_label)

        self.live_log = LiveLogView()
        self.live_log.setFixedHeight(168)
        self.live_log.setPlaceholderText(
            "Здесь построчно появляется ход работы агента: планирование LLM, "
            "выбор инструментов, результаты и итоговый вывод."
        )
        layout.addWidget(self.live_log)

        self.files_label = QLabel()
        self.files_label.setTextFormat(Qt.TextFormat.RichText)
        self.files_label.setOpenExternalLinks(False)
        self.files_label.setWordWrap(True)
        self.files_label.setVisible(False)
        self.files_label.setStyleSheet("color:#8ec3ff; font-size:12px; padding:2px 0;")
        self.files_label.linkActivated.connect(open_local_path)
        layout.addWidget(self.files_label)

        # Пошаговая лента выполнения.
        feed_scroll = QScrollArea()
        feed_scroll.setWidgetResizable(True)
        feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        feed_host = QWidget()
        self._feed_layout = QVBoxLayout(feed_host)
        self._feed_layout.setContentsMargins(0, 6, 2, 6)
        self._feed_layout.setSpacing(7)
        self._build_stage_cards()
        self._feed_layout.addStretch(1)
        feed_scroll.setWidget(feed_host)
        layout.addWidget(feed_scroll, 1)

        container.setStyleSheet(
            "#centerArea {"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0d111a, stop:0.55 #101827, stop:1 #0b1018);"
            "}"
        )
        return container

    def _build_buttons(self) -> QHBoxLayout:
        """Ряд основных действий: Создать, Сохранить, Сбросить и Остановить."""
        self.create_button = QPushButton("Создать")
        self.save_button = QPushButton("Сохранить")
        self.reset_button = QPushButton("Сбросить")
        self.stop_button = QPushButton("Остановить")

        secondary = (
            "QPushButton { background:#232733; color:#e6e9ef; border:1px solid #333846;"
            "border-radius:8px; padding:9px 14px; font-size:12px; font-weight:600; }"
            "QPushButton:hover { background:#2b3040; }"
            "QPushButton:disabled { color:#5a5f6b; border-color:#2a2e39; }"
        )
        primary = (
            "QPushButton { background:#2f6bff; color:#ffffff; border:none;"
            "border-radius:8px; padding:9px 16px; font-size:12px; font-weight:700; }"
            "QPushButton:hover { background:#3f79ff; }"
            "QPushButton:disabled { background:#26324f; color:#8b93a7; }"
        )
        stop_style = (
            "QPushButton { background:#a12727; color:#ffffff; border:none;"
            "border-radius:8px; padding:9px 16px; font-size:12px; font-weight:700; }"
            "QPushButton:hover { background:#c23232; }"
            "QPushButton:disabled { background:#3a2626; color:#8b7676; }"
        )
        for button in (self.save_button, self.reset_button):
            button.setStyleSheet(secondary)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.setStyleSheet(primary)
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setStyleSheet(stop_style)
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setEnabled(False)

        # Кнопки, которые блокируются на время фоновой работы агента.
        self._action_buttons = [
            self.create_button,
            self.save_button,
            self.reset_button,
        ]

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.create_button)
        row.addWidget(self.save_button)
        row.addWidget(self.reset_button)
        row.addWidget(self.stop_button)
        row.addStretch(1)
        return row

    def _build_human_panel(self) -> QFrame:
        """Панель участия человека: вопрос/просьба, варианты ответа и свой вариант."""
        panel = QFrame()
        panel.setObjectName("humanPanel")
        panel.setStyleSheet(
            "#humanPanel { background:#241d12; border:1px solid #8a6d15;"
            "border-radius:10px; }"
            "QLabel { color:#f0e6cf; }"
            "QRadioButton { color:#f0e6cf; font-size:12px; padding:2px 0; }"
            "QLineEdit { background:#12141a; color:#e6e9ef; border:1px solid #4a4030;"
            "border-radius:6px; padding:6px; font-size:12px; }"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        # Панель не должна сжиматься меньше, чем нужно её содержимому, иначе
        # вопрос и варианты накладываются друг на друга.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.human_title = QLabel("Агенту требуется ваше участие")
        self.human_title.setStyleSheet(
            "font-size:14px; font-weight:700; color:#ffdf9e;"
        )
        layout.addWidget(self.human_title)

        self.human_question = QLabel()
        self.human_question.setWordWrap(True)
        self.human_question.setStyleSheet("font-size:13px; color:#f4ecd8;")
        layout.addWidget(self.human_question)

        self.human_plan = QLabel()
        self.human_plan.setWordWrap(True)
        self.human_plan.setStyleSheet("font-size:11px; color:#c9b98f;")
        layout.addWidget(self.human_plan)

        self._human_options_host = QWidget()
        self._human_options_layout = QVBoxLayout(self._human_options_host)
        self._human_options_layout.setContentsMargins(0, 0, 0, 0)
        self._human_options_layout.setSpacing(4)
        self._human_options_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Если вариантов много — они прокручиваются внутри панели, а не
        # наезжают друг на друга и не растягивают экран.
        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.Shape.NoFrame)
        options_scroll.setMaximumHeight(220)
        options_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        options_scroll.setStyleSheet("QScrollArea { background:transparent; }")
        options_scroll.setWidget(self._human_options_host)
        layout.addWidget(options_scroll)

        self._human_button_group = QButtonGroup(panel)

        self.human_custom_edit = QLineEdit()
        self.human_custom_edit.setPlaceholderText("Свой вариант ответа…")
        layout.addWidget(self.human_custom_edit)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.human_continue_button = QPushButton("Продолжить")
        self.human_continue_button.setStyleSheet(
            "QPushButton { background:#1f7a3d; color:#ffffff; border:none;"
            "border-radius:8px; padding:9px 16px; font-size:12px; font-weight:700; }"
            "QPushButton:hover { background:#248c47; }"
            "QPushButton:disabled { background:#274a34; color:#8bb59a; }"
        )
        self.human_continue_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.human_continue_button.clicked.connect(self.continue_after_human)
        actions.addWidget(self.human_continue_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        return panel

    def _build_stage_cards(self) -> None:
        """Создать карточки стадий в ленте."""
        last_index = len(STAGE_ORDER)
        for index, (stage_id, title, subtitle) in enumerate(STAGE_ORDER, start=1):
            card = StageCard(
                index,
                stage_id,
                title,
                subtitle,
                index == last_index,
                self.select_stage,
            )
            self._stage_cards[stage_id] = card
            self._feed_layout.addWidget(card)

    def _build_details_panel(self) -> QWidget:
        """Правая панель деталей выбранной стадии + dev-вкладки."""
        panel = QWidget()
        panel.setObjectName("detailsPanel")
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        header = QLabel("Детали шага")
        header.setStyleSheet("font-size:16px; font-weight:800; color:#f6f8ff;")
        layout.addWidget(header)

        self.detail_title = QLabel("Запрос пользователя")
        self.detail_title.setStyleSheet(
            "font-size:13px; font-weight:700; color:#dfe7f7;"
        )
        self.detail_title.setWordWrap(True)
        layout.addWidget(self.detail_title)

        self.detail_status = QLabel()
        self.detail_status.setStyleSheet(
            "font-size:12px; padding:6px 10px; border-radius:9px;"
            "background:#111a29; border:1px solid #263247;"
        )
        layout.addWidget(self.detail_status)

        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setStyleSheet(
            "background:#0f1624; color:#d8e0ee; border:1px solid #263247;"
            "border-radius:13px; padding:12px; font-size:12px;"
            "selection-background-color:#2f6bff;"
        )
        layout.addWidget(self.detail_view, 1)

        # --- Раздел для разработчика (JSON и таблицы) ---
        self.dev_toggle = QPushButton("▸ Для разработчика (JSON и таблицы)")
        self.dev_toggle.setCheckable(True)
        self.dev_toggle.setStyleSheet(
            "QPushButton { text-align:left; background:#111a29; color:#8fa1bd;"
            "border:1px solid #243047; border-radius:10px; padding:8px 10px;"
            "font-size:11px; font-weight:700; }"
            "QPushButton:hover { color:#d7e3f8; border-color:#536b99; }"
            "QPushButton:checked { color:#e8f0ff; background:#172235; }"
        )
        self.dev_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.dev_toggle)

        self._dev_container = self._build_dev_tabs()
        self._dev_container.setVisible(False)
        layout.addWidget(self._dev_container, 1)

        panel.setStyleSheet(
            "#detailsPanel {"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #0b1018, stop:0.65 #0d1420, stop:1 #101827);"
            "border-left:1px solid #202b3f;"
            "}"
        )
        return panel

    def _build_dev_tabs(self) -> QWidget:
        """Вкладки разработчика (сырые данные и JSON)."""
        self.tabs = QTabWidget()
        self.general_output = QTextEdit()
        self.general_output.setReadOnly(True)
        self.data_table = QTableWidget()
        self.tools_table = QTableWidget()
        self.graph_table = QTableWidget()
        self.json_output = QTextEdit()
        self.json_output.setReadOnly(True)
        for table in (self.data_table, self.tools_table, self.graph_table):
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabs.addTab(self.general_output, "Общее")
        self.tabs.addTab(self.data_table, "Данные")
        self.tabs.addTab(self.tools_table, "Инструменты")
        self.tabs.addTab(self.graph_table, "Граф")
        self.tabs.addTab(self.json_output, "JSON")

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(self.tabs)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return host

    def _connect_signals(self) -> None:
        """Связать кнопки со слотами (логика конструктора не меняется)."""
        self.create_button.clicked.connect(self.create_validate_and_run)
        self.save_button.clicked.connect(self.save_agent)
        self.reset_button.clicked.connect(self.clear)
        self.stop_button.clicked.connect(self.request_stop)
        self.dev_toggle.toggled.connect(self._toggle_dev)

    def _toggle_dev(self, checked: bool) -> None:
        """Показать или скрыть раздел разработчика."""
        self._dev_container.setVisible(checked)
        arrow = "▾" if checked else "▸"
        self.dev_toggle.setText(f"{arrow} Для разработчика (JSON и таблицы)")

    # ---------------------------------------------------- background flow

    def _is_busy(self) -> bool:
        """Вернуть True, если уже выполняется фоновая операция."""
        return self._thread is not None

    def _append_log(self, message: str) -> None:
        """Добавить строку в живой лог хода выполнения."""
        self.live_log.append(message)
        scrollbar = self.live_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Включить/выключить кнопки действий на время фоновой операции."""
        for button in self._action_buttons:
            button.setEnabled(enabled)

    def _run_in_background(
        self,
        job: Callable[[Callable[[str], None]], object],
        on_completed: Callable[[object], None],
        on_failed: Callable[[str], None],
    ) -> None:
        """Запустить job в QThread, транслируя прогресс в живой лог."""
        if self._is_busy():
            show_info(
                self,
                "Идёт выполнение",
                "Дождитесь завершения текущей операции.",
            )
            return

        self._set_buttons_enabled(False)
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
        self._set_buttons_enabled(True)

    def request_stop(self) -> None:
        """Запросить остановку выполняющегося агента (кооперативно, между шагами)."""
        if not self._is_busy():
            return
        self._cancel_event.set()
        self.stop_button.setEnabled(False)
        self._append_log("⏹ Запрошена остановка агента. Останавливаю после текущего шага…")

    # -------------------------------------------------------------- actions

    def build_preview(self) -> None:
        """Построить AgentSpec preview в фоне без сохранения и запуска."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return
        if self._is_busy():
            return

        self._reset_stages()
        self.live_log.clear()
        self._last_request = user_request
        self._set_stage(STAGE_REQUEST, "passed", _short(user_request), user_request)
        self._set_running(STAGE_PLAN)
        self.select_stage(STAGE_PLAN)

        service = self._container.agent_service

        def job(progress: Callable[[str], None]) -> object:
            progress("🧩 Строю план агента через LLM…")
            spec = service.build_preview(user_request)
            progress("✅ План построен.")
            return spec

        self._run_in_background(job, self._on_preview_completed, self._on_preview_failed)

    def _on_preview_completed(self, spec: object) -> None:
        """Отобразить построенный preview AgentSpec."""
        assert isinstance(spec, AgentSpec)
        self._preview_agent = spec
        self._render_preview(spec)
        self._render_plan_stages(spec)
        self.select_stage(STAGE_PLAN)

    def _on_preview_failed(self, message: str) -> None:
        """Показать ошибку построения плана."""
        self._set_stage(STAGE_PLAN, "failed", "Не удалось построить план", message)
        self._append_log(f"⚠ Ошибка предпросмотра: {message}")
        show_error(self, "Ошибка предпросмотра", message)

    def check_tools(self) -> None:
        """Проверить регистрацию выбранных инструментов в ToolRegistry."""
        if self._preview_agent is None:
            self.build_preview()
        if self._preview_agent is None:
            return

        registry = getattr(self._container, "tool_registry", None)
        tools = list(self._preview_agent.tools)
        lines: list[str] = []
        missing: list[str] = []
        has_check = registry is not None and hasattr(registry, "has_tool")
        for tool in tools:
            if has_check:
                registered = bool(registry.has_tool(tool.tool_name))
            else:
                registered = None
            if registered is True:
                lines.append(f"✓ {tool.tool_name} — зарегистрирован")
            elif registered is False:
                lines.append(f"✕ {tool.tool_name} — НЕ зарегистрирован")
                missing.append(tool.tool_name)
            else:
                lines.append(f"• {tool.tool_name} — статус реестра недоступен")

        if not has_check:
            status = "warning"
            subtitle = "Реестр инструментов недоступен в этом контексте"
        elif missing:
            status = "failed"
            subtitle = (
                f"{len(tools) - len(missing)} из {len(tools)} зарегистрированы, "
                f"{len(missing)} отсутствуют"
            )
        else:
            status = "passed"
            subtitle = f"Все {len(tools)} инструментов зарегистрированы"

        detail = "Проверка регистрации инструментов:\n\n" + "\n".join(lines)
        if missing:
            detail += (
                "\n\nЧто исправить:\n"
                "- Зарегистрировать отсутствующие инструменты в ToolRegistry;\n"
                "- Повторно запустить проверку инструментов."
            )
        self._set_stage(STAGE_CHECK, status, subtitle, detail)
        self.select_stage(STAGE_CHECK)

    def validate_agent(self) -> None:
        """Построить preview (при необходимости) и выполнить пробную проверку в фоне."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request and self._preview_agent is None:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return
        if self._is_busy():
            return

        request = user_request or self._last_request
        self._last_request = request
        existing_spec = self._preview_agent
        if existing_spec is None:
            self._reset_stages()
            self._set_stage(STAGE_REQUEST, "passed", _short(request), request)
        self.live_log.clear()
        self._set_running(STAGE_TRIAL)
        self.select_stage(STAGE_TRIAL)

        service = self._container.agent_service

        def job(progress: Callable[[str], None]) -> object:
            spec = existing_spec
            if spec is None:
                progress("🧩 Строю план агента через LLM…")
                spec = service.build_preview(request)
                progress("✅ План построен. Запускаю пробный прогон…")
            validation = service.validate_agent(
                spec,
                request,
                progress_callback=progress,
            )
            return (spec, validation)

        self._run_in_background(
            job,
            self._on_validate_completed,
            self._on_validate_failed,
        )

    def _on_validate_completed(self, result: object) -> None:
        """Отобразить результат пробной проверки агента."""
        spec, validation = result
        self._preview_agent = spec
        self._render_preview(spec)
        self._render_plan_stages(spec)
        self._apply_validation(validation)
        self.select_stage(STAGE_RESULT)
        show_info(self, "Проверка агента", validation.summary)

    def _on_validate_failed(self, message: str) -> None:
        """Показать ошибку пробного запуска."""
        self._set_stage(STAGE_TRIAL, "failed", "Ошибка пробного запуска", message)
        self._append_log(f"⚠ Ошибка проверки агента: {message}")
        show_error(self, "Ошибка проверки агента", message)

    def create_validate_and_run(self) -> None:
        """Собрать, проверить и запустить агента в фоне при успешной проверке."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return
        if self._is_busy():
            return

        self._reset_stages()
        self.live_log.clear()
        self.files_label.setVisible(False)
        self._cancel_event.clear()
        self._last_request = user_request
        self._set_stage(STAGE_REQUEST, "passed", _short(user_request), user_request)
        self._set_running(STAGE_PLAN)
        self.select_stage(STAGE_TRIAL)

        service = self._container.agent_service
        cancel_event = self._cancel_event
        attachment_paths = list(self._attachment_paths)

        def job(progress: Callable[[str], None]) -> object:
            return service.create_validate_and_run_once(
                user_request,
                progress_callback=progress,
                cancel_callback=cancel_event.is_set,
                attachment_paths=attachment_paths,
            )

        self._run_in_background(
            job,
            self._on_create_run_completed,
            self._on_create_run_failed,
        )

    def _on_create_run_completed(self, result: object) -> None:
        """Отобразить результат «собрать, проверить и запустить»."""
        agent_spec, validation, state = result
        self._preview_agent = agent_spec
        self._render_preview(agent_spec)
        self._render_plan_stages(agent_spec)
        self._apply_validation(validation)
        self.select_stage(STAGE_RESULT)
        if state is None:
            self._hide_human_panel()
            show_info(self, "Агент не запущен", validation.summary)
            return
        if self._is_awaiting_human(state):
            self._prompt_human(agent_spec, state)
            return
        self._hide_human_panel()
        self._show_produced_files(agent_spec, state)
        show_info(
            self,
            "Агент запущен",
            f"Проверка пройдена, run_id={state.run_id}, status={state.status.value}",
        )

    def _show_produced_files(self, agent_spec: AgentSpec, state: object) -> None:
        """Показать ссылки на созданные агентом файлы и на его рабочую папку."""
        files = collect_produced_files(state)
        folder = None
        service = self._container.agent_service
        if hasattr(service, "agent_workspace_dir"):
            folder = service.agent_workspace_dir(agent_spec.agent_id)
        html = build_file_links_html(files, folder)
        if html:
            self.files_label.setText(html)
            self.files_label.setVisible(True)
        else:
            self.files_label.setVisible(False)

    @staticmethod
    def _is_awaiting_human(state: object) -> bool:
        """Проверить, приостановлен ли запуск и ждёт участия человека."""
        return getattr(state, "status", None) in {
            AgentRunStatus.PAUSED_FOR_HUMAN,
            AgentRunStatus.PAUSED_FOR_CREDENTIALS,
        }

    def _prompt_human(self, agent_spec: AgentSpec, state: object) -> None:
        """Показать панель участия человека по приостановленному состоянию."""
        self._paused_agent = agent_spec
        self._paused_state = state
        approval = getattr(state, "pending_human_approval", None)
        variables = getattr(state, "variables", {}) or {}
        if approval is not None:
            question = approval.question
            options = list(approval.options)
        else:
            question = variables.get(
                "credential_request_reason", "Агенту требуется ваше участие."
            )
            options = ["Я выполнил(а) требуемое действие"]

        self.human_question.setText(question)
        plan = variables.get("human_plan_ahead")
        if plan:
            self.human_plan.setText(f"После вашего ответа агент планирует: {plan}")
            self.human_plan.setVisible(True)
        else:
            self.human_plan.setVisible(False)
        self._populate_human_options(options)
        self.human_custom_edit.clear()
        self.human_continue_button.setEnabled(True)
        self._human_panel.setVisible(True)
        self._append_log("⏸ Агент ожидает вашего ответа/действия. Ответьте и нажмите «Продолжить».")

    def _populate_human_options(self, options: list[str]) -> None:
        """Перестроить радиокнопки вариантов ответа + «Свой вариант»."""
        for radio, _ in self._human_radios:
            self._human_button_group.removeButton(radio)
            radio.setParent(None)
            radio.deleteLater()
        self._human_radios = []
        while self._human_options_layout.count():
            item = self._human_options_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)

        for index, option in enumerate(options):
            radio = self._add_human_option_row(option)
            self._human_radios.append((radio, option))
            if index == 0:
                radio.setChecked(True)

        # Последний вариант — всегда свой ответ (значение берётся из поля ввода).
        custom_radio = self._add_human_option_row("Свой вариант ответа")
        self._human_radios.append((custom_radio, None))
        custom_radio.toggled.connect(self._on_custom_radio_toggled)

    def _add_human_option_row(self, option: str) -> QRadioButton:
        """Добавить вариант: радиокнопка + переносимый по словам текст."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        radio = QRadioButton()
        self._human_button_group.addButton(radio)
        label = QLabel(option)
        label.setWordWrap(True)
        label.setStyleSheet("color:#f0e6cf; font-size:12px;")
        label.mousePressEvent = lambda _event, r=radio: r.setChecked(True)
        row_layout.addWidget(radio, 0, Qt.AlignmentFlag.AlignTop)
        row_layout.addWidget(label, 1)
        self._human_options_layout.addWidget(row)
        return radio

    def _on_custom_radio_toggled(self, checked: bool) -> None:
        """Если выбран свой вариант — сфокусировать поле ввода."""
        if checked:
            self.human_custom_edit.setFocus()

    def _selected_human_answer(self) -> str | None:
        """Вернуть выбранный ответ человека (вариант или свой текст)."""
        for radio, option in self._human_radios:
            if not radio.isChecked():
                continue
            if option is None:
                return self.human_custom_edit.text().strip()
            return option
        # Если ничего не выбрано, но введён свой текст — используем его.
        return self.human_custom_edit.text().strip() or None

    def _hide_human_panel(self) -> None:
        """Скрыть панель участия человека и очистить контекст паузы."""
        self._human_panel.setVisible(False)
        self._paused_agent = None
        self._paused_state = None

    def continue_after_human(self) -> None:
        """Продолжить работу агента после ответа/действия человека."""
        if self._paused_state is None or self._paused_agent is None:
            return
        if self._is_busy():
            return
        answer = self._selected_human_answer()
        if not answer:
            show_error(
                self,
                "Нужен ответ",
                "Выберите вариант или введите свой ответ, затем нажмите «Продолжить».",
            )
            return

        agent_spec = self._paused_agent
        state = self._paused_state
        self._human_panel.setVisible(False)
        self._cancel_event.clear()
        self._set_running(STAGE_TRIAL)
        self.select_stage(STAGE_TRIAL)
        self._append_log(f"▶ Продолжаю после ответа человека: {answer}")

        service = self._container.agent_service
        cancel_event = self._cancel_event

        def job(progress: Callable[[str], None]) -> object:
            return service.resume_after_human(
                agent_spec,
                state,
                answer,
                approved=True,
                progress_callback=progress,
                cancel_callback=cancel_event.is_set,
            )

        self._run_in_background(
            job,
            self._on_create_run_completed,
            self._on_create_run_failed,
        )

    def _on_create_run_failed(self, message: str) -> None:
        """Показать ошибку сборки/проверки/запуска."""
        self._set_stage(STAGE_PLAN, "failed", "Не удалось собрать агента", message)
        self._append_log(f"⚠ Ошибка проверки и запуска: {message}")
        show_error(self, "Ошибка проверки и запуска", message)

    def save_agent(self) -> None:
        """Сохранить preview или создать и сохранить агента из запроса."""
        user_request = self.request_edit.toPlainText().strip()
        if not user_request and self._preview_agent is None:
            show_error(self, "Пустой запрос", "Введите запрос для создания агента.")
            return

        service = self._container.agent_service
        try:
            if self._preview_agent is not None:
                source = self._preview_agent
                request = self._last_request or user_request
            else:
                source = service.build_preview(user_request)
                request = user_request
            if hasattr(service, "finalize_and_save_agent"):
                agent_spec = service.finalize_and_save_agent(source, request)
            else:
                agent_spec = source
                service.save_agent(agent_spec)
            self._preview_agent = agent_spec
            self._last_request = request
            self._render_preview(agent_spec)
            self._render_plan_stages(agent_spec)
        except Exception as exc:
            show_error(self, "Ошибка сохранения агента", exc)
            return

        show_info(
            self,
            "Агент сохранён",
            f"«{agent_spec.name}» сохранён в каталоге.",
        )

    def attach_files(self) -> None:
        """Выбрать файлы, которые агент прочитает и получит в свою рабочую папку."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Прикрепить файлы для агента",
            "",
            "Файлы (*.xlsx *.csv *.txt *.json *.md);;Все файлы (*.*)",
        )
        if not paths:
            return
        for path in paths:
            if path not in self._attachment_paths:
                self._attachment_paths.append(path)
        self._update_attach_label()

    def clear_attachments(self) -> None:
        """Убрать все прикреплённые файлы."""
        self._attachment_paths = []
        self._update_attach_label()

    def _update_attach_label(self) -> None:
        """Обновить подпись со списком прикреплённых файлов."""
        if not self._attachment_paths:
            self.attach_label.setText("Файлы не прикреплены")
            return
        from pathlib import Path

        names = ", ".join(Path(path).name for path in self._attachment_paths)
        self.attach_label.setText(f"Прикреплено: {names}")

    def clear(self) -> None:
        """Очистить запрос, preview и ленту стадий."""
        if self._is_busy():
            show_info(self, "Идёт выполнение", "Дождитесь завершения операции.")
            return
        self._preview_agent = None
        self._last_request = ""
        self.clear_attachments()
        self._hide_human_panel()
        self.request_edit.clear()
        self.live_log.clear()
        self.files_label.setVisible(False)
        self.general_output.clear()
        self.json_output.clear()
        set_table_rows(self.data_table, [], self._data_headers())
        set_table_rows(self.tools_table, [], self._tool_headers())
        set_table_rows(self.graph_table, [], self._graph_headers())
        self._reset_stages()
        self.select_stage(STAGE_REQUEST)

    # ------------------------------------------------------- stage helpers

    def _reset_stages(self) -> None:
        """Сбросить все стадии в pending с исходными подписями."""
        for stage_id, _title, subtitle in STAGE_ORDER:
            card = self._stage_cards[stage_id]
            card.set_status("pending")
            card.set_subtitle(subtitle)
            self._stage_details[stage_id] = "Стадия ещё не выполнялась."
        self._stage_details[STAGE_DEV] = (
            "Технические детали доступны в разделе «Для разработчика» ниже: "
            "вкладки Общее / Данные / Инструменты / Граф / JSON."
        )

    def _set_stage(
        self,
        stage_id: str,
        status: str,
        subtitle: str,
        detail: str,
    ) -> None:
        """Обновить статус, подпись и детали стадии."""
        card = self._stage_cards[stage_id]
        card.set_status(status)
        card.set_subtitle(subtitle)
        self._stage_details[stage_id] = detail
        if self._selected_stage == stage_id:
            self.select_stage(stage_id)

    def _set_running(self, stage_id: str) -> None:
        """Пометить стадию как выполняющуюся."""
        self._stage_cards[stage_id].set_status("running")

    def select_stage(self, stage_id: str) -> None:
        """Показать детали выбранной стадии в правой панели."""
        self._selected_stage = stage_id
        for other_id, card in self._stage_cards.items():
            card.set_selected(other_id == stage_id)
        card = self._stage_cards[stage_id]
        title = next(t for sid, t, _ in STAGE_ORDER if sid == stage_id)
        self.detail_title.setText(title)
        label, bg, fg, icon = STATUS_STYLE[card._status]
        self.detail_status.setText(f"{icon}  Статус: {label}")
        self.detail_status.setStyleSheet(
            f"color:{fg}; background:{bg}; font-size:12px; font-weight:700;"
            "padding:6px 10px; border-radius:9px; border:1px solid #2b3852;"
        )
        self.detail_view.setPlainText(self._stage_details.get(stage_id, ""))
        if stage_id == STAGE_DEV:
            self.dev_toggle.setChecked(True)

    # --------------------------------------------------------- rendering

    def _render_plan_stages(self, agent_spec: AgentSpec) -> None:
        """Заполнить стадии план/инструменты/граф по AgentSpec."""
        plan_detail = "\n".join(
            [
                f"Название: {agent_spec.name}",
                f"Описание: {agent_spec.description}",
                "",
                f"Цель: {agent_spec.goal.main_goal}",
                "",
                "Критерии успеха:",
                *[f"- {item}" for item in agent_spec.goal.success_criteria],
                "",
                "Запрещённые действия:",
                *[f"- {item}" for item in agent_spec.goal.forbidden_actions],
            ]
        )
        self._set_stage(
            STAGE_PLAN, "passed", _short(agent_spec.goal.main_goal), plan_detail
        )

        registry = getattr(self._container, "tool_registry", None)
        has_check = registry is not None and hasattr(registry, "has_tool")
        tool_lines: list[str] = []
        for tool in agent_spec.tools:
            reg = ""
            if has_check:
                reg = (
                    " [зарегистрирован]"
                    if registry.has_tool(tool.tool_name)
                    else " [НЕ зарегистрирован]"
                )
            approval = " (нужно подтверждение)" if tool.requires_human_approval else ""
            tool_lines.append(
                f"• {tool.tool_name} — {tool.action_level.value}{approval}{reg}"
            )
        self._set_stage(
            STAGE_TOOLS,
            "passed",
            f"{len(agent_spec.tools)} инструментов выбрано",
            "Выбранные инструменты:\n\n" + "\n".join(tool_lines),
        )

        graph_lines = [
            f"{node.node_id} [{node.node_type.value}] {node.title}"
            + (f" → {node.tool_name}" if node.tool_name else "")
            for node in agent_spec.graph_nodes
        ]
        self._set_stage(
            STAGE_GRAPH,
            "passed",
            f"{len(agent_spec.graph_nodes)} узлов графа",
            "Граф выполнения:\n\n" + "\n".join(graph_lines),
        )

    def _apply_validation(self, validation) -> None:
        """Заполнить стадии проверки/качества/итога по результату валидации."""
        text = self._format_general(self._preview_agent) + "\n\n" + (
            self._format_validation(validation)
        )
        self.general_output.setPlainText(text)

        status = validation.status.value
        registration_failed = any(
            "не зарегистрирован" in item.lower() for item in validation.errors
        )
        if registration_failed:
            self._set_stage(
                STAGE_CHECK,
                "failed",
                "Не все инструменты зарегистрированы",
                "\n".join(
                    [item for item in validation.errors if "зарегистр" in item.lower()]
                )
                or "Есть незарегистрированные инструменты.",
            )
        else:
            self._set_stage(
                STAGE_CHECK,
                "passed",
                "Инструменты зарегистрированы",
                "Все инструменты плана прошли проверку регистрации.",
            )

        trial_status = {
            "passed": "passed",
            "failed": "failed",
            "needs_human": "needs_human",
            "needs_credentials": "needs_credentials",
            "not_checked": "pending",
        }.get(status, "warning")
        trial_detail = "\n".join(
            [
                f"Статус: {status}",
                f"run_id: {validation.run_id}",
                f"summary: {validation.summary}",
                "",
                "Ошибки:" if validation.errors else "Ошибок нет.",
                *[f"- {item}" for item in validation.errors],
            ]
        )
        self._set_stage(STAGE_TRIAL, trial_status, validation.summary, trial_detail)

        if validation.critical_errors:
            quality_status = "failed"
            quality_subtitle = "Критические проблемы результата"
        elif validation.warnings:
            quality_status = "warning"
            quality_subtitle = f"{len(validation.warnings)} предупреждений"
        elif status == "passed":
            quality_status = "passed"
            quality_subtitle = "Результат достаточен"
        else:
            quality_status = "warning"
            quality_subtitle = "Требуется внимание"
        quality_detail_lines: list[str] = []
        if validation.critical_errors:
            quality_detail_lines.append("Критические ошибки:")
            quality_detail_lines += [f"- {i}" for i in validation.critical_errors]
        if validation.warnings:
            quality_detail_lines.append("Предупреждения:")
            quality_detail_lines += [f"- {i}" for i in validation.warnings]
        if validation.tool_result_checks:
            quality_detail_lines.append("")
            quality_detail_lines.append("Проверка обязательных инструментов:")
            for check in validation.tool_result_checks:
                quality_detail_lines.append(
                    f"- {check.get('tool_name')}: "
                    f"{'ok' if check.get('ok') else 'ошибка'} "
                    f"({check.get('error_type') or '—'})"
                )
        if not quality_detail_lines:
            quality_detail_lines = ["Результат признан достаточным для цели агента."]
        self._set_stage(
            STAGE_QUALITY,
            quality_status,
            quality_subtitle,
            "\n".join(quality_detail_lines),
        )

        result_status = trial_status
        result_detail_lines = [
            f"Итог проверки: {status}",
            f"summary: {validation.summary}",
            "",
            "Итоговый вывод агента:",
            validation.final_message or "Итоговый вывод пока не сформирован.",
        ]
        if validation.errors:
            result_detail_lines.append("")
            result_detail_lines.append("Причины/ошибки:")
            result_detail_lines += [f"- {item}" for item in validation.errors]
        if validation.suggested_fixes:
            result_detail_lines.append("")
            result_detail_lines.append("Что делать дальше:")
            result_detail_lines += [f"- {i}" for i in validation.suggested_fixes]
        self._set_stage(
            STAGE_RESULT,
            result_status,
            validation.summary,
            "\n".join(result_detail_lines),
        )
        self._set_stage(
            STAGE_DEV,
            "passed",
            "Технические детали готовы",
            self._stage_details[STAGE_DEV],
        )

    def _render_preview(self, agent_spec: AgentSpec) -> None:
        """Показать AgentSpec во вкладках разработчика (сырые данные)."""
        self.general_output.setPlainText(self._format_general(agent_spec))
        set_table_rows(
            self.data_table,
            [
                [
                    item.name,
                    item.description,
                    item.required,
                    item.can_agent_find,
                    item.default_value,
                    item.ask_human_if_missing,
                ]
                for item in agent_spec.data_requirements
            ],
            self._data_headers(),
        )
        set_table_rows(
            self.tools_table,
            [
                [
                    tool.tool_name,
                    tool.action_level.value,
                    tool.requires_human_approval,
                    tool.allowed,
                ]
                for tool in agent_spec.tools
            ],
            self._tool_headers(),
        )
        set_table_rows(
            self.graph_table,
            [
                [
                    node.node_id,
                    node.node_type.value,
                    node.title,
                    node.tool_name,
                    node.next_on_success,
                    node.next_on_error,
                ]
                for node in agent_spec.graph_nodes
            ],
            self._graph_headers(),
        )
        self.json_output.setPlainText(
            format_json_preview(agent_spec.model_dump(mode="json"), max_chars=12000)
        )

    def _format_general(self, agent_spec: AgentSpec) -> str:
        """Сформировать общую вкладку AgentSpec."""
        lines = [
            f"Название: {agent_spec.name}",
            f"agent_id: {agent_spec.agent_id}",
            f"Описание: {agent_spec.description}",
            "",
            f"Цель: {agent_spec.goal.main_goal}",
            "Критерии успеха:",
            *[f"- {item}" for item in agent_spec.goal.success_criteria],
            "Запрещённые действия:",
            *[f"- {item}" for item in agent_spec.goal.forbidden_actions],
        ]
        return "\n".join(lines)

    def _format_validation(self, validation) -> str:
        """Сформировать текст результата пробной проверки."""
        lines = [
            "Проверка агента:",
            f"status: {validation.status.value}",
            f"run_id: {validation.run_id}",
            f"summary: {validation.summary}",
            "",
            "Итоговый вывод:",
            validation.final_message or "Итоговый вывод пока не сформирован.",
            "",
            "errors:",
            *[f"- {item}" for item in validation.errors],
            "critical_errors:",
            *[f"- {item}" for item in validation.critical_errors],
            "warnings:",
            *[f"- {item}" for item in validation.warnings],
            "suggested_fixes:",
            *[f"- {item}" for item in validation.suggested_fixes],
        ]
        if validation.tool_result_checks:
            lines.extend(["", "Проверка обязательных инструментов:"])
            for check in validation.tool_result_checks:
                lines.extend(
                    [
                        f"- tool_name: {check.get('tool_name')}",
                        f"  node_id: {check.get('node_id')}",
                        f"  critical: {check.get('critical')}",
                        f"  error_type: {check.get('error_type')}",
                        f"  error_message: {check.get('error_message')}",
                        f"  recommendation: {check.get('recommendation')}",
                    ]
                )
        if validation.output_data:
            lines.extend(
                [
                    "",
                    "Структурированный результат:",
                    format_json_preview(validation.output_data, max_chars=4000),
                ]
            )
        return "\n".join(lines)

    def _data_headers(self) -> list[str]:
        """Вернуть заголовки таблицы data requirements."""
        return [
            "name",
            "description",
            "required",
            "can_agent_find",
            "default_value",
            "ask_human_if_missing",
        ]

    def _tool_headers(self) -> list[str]:
        """Вернуть заголовки таблицы tools."""
        return ["tool_name", "action_level", "requires_human_approval", "allowed"]

    def _graph_headers(self) -> list[str]:
        """Вернуть заголовки таблицы graph."""
        return [
            "node_id",
            "node_type",
            "title",
            "tool_name",
            "next_on_success",
            "next_on_error",
        ]
