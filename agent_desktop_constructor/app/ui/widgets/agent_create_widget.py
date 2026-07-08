"""Страница создания агента в стиле пошагового workflow.

UI-слой не меняет внутреннюю логику конструктора: используются те же вызовы
``agent_service`` (build_preview / validate_agent / create_validate_and_run_once /
save_agent / create_agent_from_request). Экран лишь показывает наглядно, что агент
построил, что проверяет, что запускает и почему что-то не сработало.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from threading import Event
from typing import Callable
from urllib import error, request

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
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
    QMenu,
    QPushButton,
    QProgressBar,
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

from agent_desktop_constructor.app.core.bootstrap import (
    ApplicationContainer,
    build_application_container,
)
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


@dataclass(frozen=True)
class UiModelOption:
    """Модель для селекта UI."""

    model_id: str
    label: str
    supports_reasoning: bool = False
    modes: tuple[str, ...] = ()


DEFAULT_UI_MODEL_OPTIONS: tuple[UiModelOption, ...] = (
    UiModelOption(
        "chatgpt",
        "Chat-GPT 5.5",
        supports_reasoning=True,
        modes=("internal", "reason"),
    ),
    UiModelOption("lmstudio", "LM Studio (gpt-oss-120b)"),
)

BADGE_SELECT_MENU_STYLE = """
QMenu {
    background: #0f172a;
    color: #dbeafe;
    border: 1px solid #1e3a5f;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #1d4ed8;
}
"""

MODEL_BADGE_STYLE = """
QPushButton {
    background: #20283a;
    color: #9da9bf;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 9px;
    padding: 3px 20px 3px 9px;
    font-size: 10px;
    font-weight: 700;
    text-align: left;
}
QPushButton:hover {
    background: #263247;
    color: #c5d0e4;
    border-color: rgba(255,255,255,0.12);
}
QPushButton:disabled {
    color: #5c6b82;
    background: #161d2c;
}
"""

REASON_BADGE_STYLE = """
QPushButton {
    background: transparent;
    color: #94a3b8;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 3px 20px 3px 9px;
    font-size: 10px;
    font-weight: 700;
    text-align: left;
}
QPushButton:hover {
    background: #20283a;
    color: #9da9bf;
    border: 1px solid rgba(255,255,255,0.07);
}
QPushButton:disabled {
    color: #475569;
    background: transparent;
    border-color: transparent;
}
"""

MODEL_REFRESH_BUTTON_STYLE = """
QPushButton {
    background: transparent;
    color: #64748b;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
}
QPushButton:hover {
    background: #20283a;
    color: #9da9bf;
    border: 1px solid rgba(255,255,255,0.07);
}
"""


def _split_model_mode(model_id: str) -> tuple[str, str | None]:
    """Разобрать selectable id вида model:internal/model:reason."""
    base, sep, mode = model_id.partition(":")
    if sep and mode in {"internal", "reason"}:
        return base, mode
    return model_id, None


def _merge_default_model_options(options: list[UiModelOption]) -> list[UiModelOption]:
    """Гарантировать, что в селекте всегда есть Chat-GPT 5.5 и LM Studio."""
    merged: dict[str, UiModelOption] = {
        option.model_id: option for option in DEFAULT_UI_MODEL_OPTIONS
    }
    for option in options:
        if option.model_id in merged:
            merged[option.model_id] = option
    return [merged["chatgpt"], merged["lmstudio"]]

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

WORKFLOW_TABS: list[tuple[str, str, str]] = [
    (STAGE_REQUEST, "Запрос", "request"),
    (STAGE_PLAN, "План", "plan"),
    (STAGE_TOOLS, "Инструменты", "tools"),
    (STAGE_GRAPH, "Граф", "graph"),
    (STAGE_CHECK, "Проверка", "check"),
    (STAGE_TRIAL, "Запуск", "launch"),
    (STAGE_QUALITY, "Качество", "quality"),
    (STAGE_RESULT, "Итог", "result"),
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

REF_BG = "#06101d"
REF_PANEL = "#08172a"
REF_PANEL_ALT = "#0a1b31"
REF_BORDER = "#16304f"
REF_BLUE = "#2f7cff"
REF_TEXT = "#e7eefc"
REF_MUTED = "#7f8ea5"


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

        center = QPointF(self.width() / 2, 29)
        radius = 11
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
            painter.drawLine(QPointF(center.x() - 4, center.y() - 4), QPointF(center.x() + 4, center.y() + 4))
            painter.drawLine(QPointF(center.x() + 4, center.y() - 4), QPointF(center.x() - 4, center.y() + 4))
        else:
            painter.setPen(self._glow_pen(color, 2.6, 230))
            painter.drawLine(QPointF(center.x(), center.y() - 7), QPointF(center.x(), center.y() + 3))
            painter.drawPoint(QPointF(center.x(), center.y() + 8))

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
        self.setMinimumHeight(56)

        self._indicator = NeonStepIndicator(index, is_last)
        self._indicator.setFixedWidth(38)
        self._indicator.setMinimumHeight(50)

        self._time = QLabel("10:42:17")
        self._time.setObjectName("stageTime")
        self._time.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel(title)
        self._title.setObjectName("stageTitle")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("stageSubtitle")
        self._subtitle.setWordWrap(True)

        self._badge = QLabel()
        self._badge.setObjectName("stageBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._chevron = QLabel("⌄")
        self._chevron.setObjectName("stageChevron")
        self._chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)
        row.addWidget(self._time, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 6, 0, 6)
        text_col.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self._title, 1)
        text_col.addLayout(title_row)
        text_col.addWidget(self._subtitle)
        row.addLayout(text_col, 1)
        row.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)

        self.set_status("pending")

    def set_status(self, status: str) -> None:
        """Обновить статус стадии и перерисовать бейдж."""
        self._status = status if status in STATUS_STYLE else "pending"
        label, bg, fg, icon = STATUS_STYLE[self._status]
        self._indicator.set_status(self._status)
        self._badge.setText(label)
        self._badge.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:9px;"
            "padding:3px 9px; font-size:10px; font-weight:700;"
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
        border = "#275d9e" if self._selected else "#15304e"
        bg = "#0d213b" if self._selected else "#08172a"
        self.setStyleSheet(
            "#stageCard {"
            f"background:{bg}; border:1px solid {border};"
            "border-radius:12px;"
            "}"
            "#stageCard:hover { border:1px solid #2f7cff; background:#0b1d34; }"
            "#stageTime { color:#52637a; font-size:11px; min-width:54px; }"
            "#stageTitle { color:#dce7f8; font-size:12px; font-weight:700; }"
            "#stageSubtitle { color:#7f8ea5; font-size:10px; line-height:1.25; }"
            "#stageBadge { border:1px solid rgba(255,255,255,0.07); }"
            "#stageChevron { color:#6f7e93; font-size:17px; min-width:18px; }"
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
            "background:#071426;"
            "border:1px solid #102844; border-radius:12px;"
            "}"
            "#liveLogHost { background:transparent; }"
            "#livePlaceholder { color:#66738b; font-size:12px; padding:8px; }"
            "#liveLogItem {"
            "background:#081a2f; border:1px solid #15304e;"
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
            f"stop:0 {color}, stop:0.009 #0c213a, stop:1 #08172a);"
            f"border:1px solid {color}; border-radius:10px;"
            "}"
        )

    @staticmethod
    def _clean_message(text: str) -> str:
        return text.lstrip("✅⚠❌⏸📎🧩🔎▶⏹ ").strip() or text


class PlanNumberCircle(QWidget):
    """Круг с номером шага, как в референсе плана."""

    def __init__(self, number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._number = number
        self._visual = "pending"
        self.setFixedSize(28, 28)

    def set_visual(self, visual: str) -> None:
        self._visual = visual
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1.5, 1.5, 25, 25)
        if self._visual == "active":
            border = QColor("#3b82f6")
            text = QColor("#eef5ff")
        elif self._visual == "passed":
            border = QColor("#4b5568")
            text = QColor("#9aa8bc")
        else:
            border = QColor("#334155")
            text = QColor("#64748b")
        pen = QPen(border, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)
        painter.setPen(text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self._number))


class PlanStatusIcon(QWidget):
    """Статус справа: зелёная галочка или синяя точка."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = "none"
        self.setFixedSize(18, 18)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._mode == "none":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._mode == "check":
            color = QColor("#22c55e")
            painter.setPen(QPen(color, 1.3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(2, 2, 14, 14))
            painter.setPen(QPen(color, 1.5))
            path = QPainterPath(QPointF(5.5, 9.2))
            path.lineTo(QPointF(8.2, 11.8))
            path.lineTo(QPointF(12.8, 6.2))
            painter.drawPath(path)
        elif self._mode == "dot":
            glow = QColor("#3b82f6")
            glow.setAlpha(60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(3, 3, 12, 12))
            painter.setBrush(QColor("#3b82f6"))
            painter.drawEllipse(QRectF(6, 6, 6, 6))


class PlanStepRow(QFrame):
    """Строка шага в блоке «План» с левой accent-полосой и статусом справа."""

    def __init__(
        self,
        index: int,
        stage_id: str,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.stage_id = stage_id
        self._status = "pending"
        self._active = False
        self.setObjectName("planStepRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(46)
        self.setMaximumHeight(52)

        self._accent = QFrame()
        self._accent.setFixedWidth(3)
        self._accent.setObjectName("planStepAccent")

        self._number = PlanNumberCircle(index)
        self._title = QLabel(title)
        self._title.setObjectName("planStepTitle")
        self._title.setWordWrap(False)
        self._status_icon = PlanStatusIcon()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 10, 0)
        row.setSpacing(10)
        row.addWidget(self._accent)
        row.addWidget(self._number, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._title, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._status_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self._apply_style()

    def set_status(self, status: str) -> None:
        self._status = status if status in STATUS_STYLE else "pending"
        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        parent = self.parent()
        while parent is not None and not hasattr(parent, "select_stage"):
            parent = parent.parent()
        if parent is not None:
            parent.select_stage(self.stage_id)
        super().mousePressEvent(event)

    def _apply_style(self) -> None:
        is_running = self._status == "running"
        is_passed = self._status == "passed"
        is_problem = self._status in {
            "failed",
            "warning",
            "needs_human",
            "needs_credentials",
        }

        if is_running:
            row_bg = "#131d2f"
            title_color = "#3b82f6"
            number_visual = "active"
            status_mode = "dot"
            accent = "#3b82f6"
        elif is_passed:
            row_bg = "rgba(21, 26, 35, 0.72)"
            title_color = "#b8c5d6"
            number_visual = "passed"
            status_mode = "check"
            accent = "transparent"
        elif is_problem:
            row_bg = "rgba(21, 26, 35, 0.72)"
            title_color = "#fbbf24" if self._status != "failed" else "#f87171"
            number_visual = "pending"
            status_mode = "none"
            accent = "transparent"
        elif self._active:
            row_bg = "#131d2f"
            title_color = "#3b82f6"
            number_visual = "active"
            status_mode = "none"
            accent = "#3b82f6"
        else:
            row_bg = "rgba(21, 26, 35, 0.55)"
            title_color = "#64748b"
            number_visual = "pending"
            status_mode = "none"
            accent = "transparent"

        self._number.set_visual(number_visual)
        self._status_icon.set_mode(status_mode)
        self._accent.setStyleSheet(f"background:{accent}; border-radius:2px;")
        self.setStyleSheet(
            "#planStepRow {"
            f"background:{row_bg}; border:none; border-radius:8px;"
            "}"
            "#planStepRow:hover { background:#172338; }"
            f"#planStepTitle {{ color:{title_color}; font-size:12px; font-weight:600; }}"
        )


class PlanStepsList(QWidget):
    """Вертикальный список шагов плана с пунктирной линией между кругами."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[PlanStepRow] = []
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(6)

    def add_step(self, row: PlanStepRow) -> None:
        self._rows.append(row)
        self._layout.addWidget(row)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if len(self._rows) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        first = self._rows[0]
        last = self._rows[-1]
        start_center = first._number.mapTo(
            self,
            QPointF(first._number.width() / 2, first._number.height() / 2),
        )
        end_center = last._number.mapTo(
            self,
            QPointF(last._number.width() / 2, last._number.height() / 2),
        )
        x = start_center.x()
        start_y = start_center.y()
        end_y = end_center.y()
        pen = QPen(QColor("#334155"), 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([3, 4])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, start_y), QPointF(x, end_y))


class BadgeSelect(QPushButton):
    """Pill-селект в стиле бейджа «Ожидает» с меню, раскрывающимся вверх."""

    currentIndexChanged = Signal(int)

    def __init__(self, *, ghost: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ghost = ghost
        self._labels: list[str] = []
        self._data: list[object] = []
        self._index = -1
        self._menu = QMenu(self)
        self._menu.setStyleSheet(BADGE_SELECT_MENU_STYLE)
        self._menu.triggered.connect(self._on_menu_action)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._open_menu)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(REASON_BADGE_STYLE if self._ghost else MODEL_BADGE_STYLE)

    def _open_menu(self) -> None:
        if not self.isEnabled() or self.count() == 0:
            return
        self._rebuild_menu()
        self._menu.adjustSize()
        anchor = self.mapToGlobal(QPoint(0, 0))
        menu_height = self._menu.sizeHint().height()
        if menu_height <= 0:
            menu_height = self.count() * 28 + 12
        self._menu.popup(QPoint(anchor.x(), anchor.y() - menu_height))

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        for index, label in enumerate(self._labels):
            action = self._menu.addAction(label)
            action.setData(index)

    def _on_menu_action(self, action) -> None:
        index = action.data()
        if index is None:
            return
        self.setCurrentIndex(int(index))

    def addItem(self, text: str, data: object | None = None) -> None:
        self._labels.append(text)
        self._data.append(data if data is not None else text)
        if self.count() == 1:
            self._set_index(0, emit=False)

    def clear(self) -> None:
        self._labels.clear()
        self._data.clear()
        self._index = -1
        self.setText("")

    def count(self) -> int:
        return len(self._labels)

    def currentIndex(self) -> int:
        return self._index

    def currentText(self) -> str:
        if self._index < 0 or self._index >= len(self._labels):
            return ""
        return self._labels[self._index]

    def currentData(self) -> object | None:
        if self._index < 0 or self._index >= len(self._data):
            return None
        return self._data[self._index]

    def setCurrentIndex(self, index: int) -> None:
        self._set_index(index, emit=True)

    def findData(self, data: object) -> int:
        for index, value in enumerate(self._data):
            if value == data:
                return index
        return -1

    def showPopup(self) -> None:
        self._open_menu()

    def hidePopup(self) -> None:
        self._menu.hide()

    def view(self) -> QMenu:
        return self._menu

    def _set_index(self, index: int, *, emit: bool) -> None:
        if index < 0 or index >= len(self._labels):
            return
        previous = self._index
        self._index = index
        self.setText(f"{self._labels[index]}  ▾")
        if emit and previous != index:
            self.currentIndexChanged.emit(index)


class ComposerIconButton(QPushButton):
    """Квадратная кнопка с line-icon для нижней панели composer."""

    def __init__(self, kind: str, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setText("")
        self.setObjectName("composerIconButton")
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(30, 30)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#94a3b8")
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._kind == "attach":
            path = QPainterPath(QPointF(14, 8))
            path.arcTo(QRectF(10, 8, 6, 6), 0, -180)
            path.lineTo(QPointF(14, 19))
            path.arcTo(QRectF(10, 16, 6, 6), 180, -180)
            painter.drawPath(path)
        elif self._kind == "database":
            painter.drawEllipse(QRectF(7, 5, 16, 5))
            painter.drawLine(QPointF(7, 7.5), QPointF(7, 20))
            painter.drawLine(QPointF(23, 7.5), QPointF(23, 20))
            painter.drawEllipse(QRectF(7, 12, 16, 5))
            painter.drawEllipse(QRectF(7, 18, 16, 5))
        elif self._kind == "grid":
            painter.drawRect(QRectF(7, 7, 7, 7))
            painter.drawRect(QRectF(16, 7, 7, 7))
            painter.drawRect(QRectF(7, 16, 7, 7))
            painter.drawRect(QRectF(16, 16, 7, 7))
        else:
            painter.drawLine(QPointF(10, 10), QPointF(8, 10))
            painter.drawLine(QPointF(8, 10), QPointF(8, 20))
            painter.drawLine(QPointF(8, 20), QPointF(10, 20))
            painter.drawLine(QPointF(20, 10), QPointF(22, 10))
            painter.drawLine(QPointF(22, 10), QPointF(22, 20))
            painter.drawLine(QPointF(22, 20), QPointF(20, 20))


class WorkflowStepIcon(QWidget):
    """Line-icon для нижней панели шагов workflow."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._active = False
        self.setFixedSize(16, 16)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def _color(self) -> QColor:
        return QColor("#3b82f6") if self._active else QColor("#64748b")

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._color()
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._kind == "request":
            painter.drawRoundedRect(QRectF(1.5, 2.5, 11, 9), 3, 3)
            painter.drawLine(QPointF(4.5, 11.5), QPointF(6.5, 14))
            for y in (5.5, 7.5, 9.5):
                painter.drawLine(QPointF(4, y), QPointF(10, y))
        elif self._kind == "plan":
            painter.drawRect(QRectF(2.5, 2.5, 11, 11))
            painter.drawLine(QPointF(8, 2.5), QPointF(8, 13.5))
            painter.drawLine(QPointF(2.5, 8), QPointF(13.5, 8))
        elif self._kind == "tools":
            painter.drawEllipse(QRectF(2.5, 4.5, 5, 5))
            painter.drawEllipse(QRectF(8.5, 6.5, 5, 5))
        elif self._kind == "graph":
            for x, y in ((3, 3), (12, 3), (3, 12), (12, 12)):
                painter.drawEllipse(QRectF(x - 1.2, y - 1.2, 2.4, 2.4))
            painter.drawLine(QPointF(4.2, 4.2), QPointF(10.8, 4.2))
            painter.drawLine(QPointF(4.2, 11.8), QPointF(10.8, 11.8))
            painter.drawLine(QPointF(4.2, 4.2), QPointF(4.2, 11.8))
            painter.drawLine(QPointF(10.8, 4.2), QPointF(10.8, 11.8))
        elif self._kind == "check":
            path = QPainterPath(QPointF(8, 2.2))
            path.lineTo(QPointF(12.8, 4.2))
            path.lineTo(QPointF(11.8, 12.2))
            path.lineTo(QPointF(4.2, 12.2))
            path.lineTo(QPointF(3.2, 4.2))
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(QPointF(6.2, 8.2), QPointF(7.8, 9.8))
            painter.drawLine(QPointF(7.8, 9.8), QPointF(10.2, 6.8))
        elif self._kind == "launch":
            painter.drawEllipse(QRectF(2.5, 2.5, 11, 11))
            painter.drawLine(QPointF(8, 5), QPointF(8, 11))
            painter.drawLine(QPointF(5, 8), QPointF(11, 8))
        elif self._kind == "quality":
            painter.drawEllipse(QRectF(5, 2.2, 6, 6))
            path = QPainterPath(QPointF(4.5, 8.2))
            path.lineTo(QPointF(11.5, 8.2))
            path.lineTo(QPointF(10, 13.5))
            path.lineTo(QPointF(6, 13.5))
            path.closeSubpath()
            painter.drawPath(path)
        else:
            path = QPainterPath(QPointF(8, 2.5))
            path.lineTo(QPointF(13, 8))
            path.lineTo(QPointF(8, 13.5))
            path.lineTo(QPointF(3, 8))
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(QPointF(8, 4.5), QPointF(8, 12.5))


class WorkflowStepConnector(QWidget):
    """Короткая пунктирная линия между вкладками workflow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 32)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#2563eb"), 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([2.5, 3.5])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        y = self.height() / 2
        painter.drawLine(QPointF(1, y), QPointF(self.width() - 1, y))


class WorkflowStepTab(QFrame):
    """Вкладка нижней панели workflow с иконкой и подписью."""

    clicked = Signal(str)

    def __init__(
        self,
        stage_id: str,
        label: str,
        icon_kind: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.stage_id = stage_id
        self._active = False
        self.setObjectName("workflowStepTab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)
        self.setMaximumHeight(34)

        self._icon = WorkflowStepIcon(icon_kind)
        self._label = QLabel(label)
        self._label.setObjectName("workflowStepLabel")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._icon.set_active(active)
        self._apply_style()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.stage_id)
        super().mousePressEvent(event)

    def _apply_style(self) -> None:
        if self._active:
            bg = "#0f2340"
            border = "#3b82f6"
            text = "#eef5ff"
        else:
            bg = "rgba(17, 24, 39, 0.55)"
            border = "#1e293b"
            text = "#64748b"
        self.setStyleSheet(
            "#workflowStepTab {"
            f"background:{bg}; border:1px solid {border}; border-radius:8px;"
            "}"
            "#workflowStepTab:hover { background:#172338; border-color:#334155; }"
            f"#workflowStepLabel {{ color:{text}; font-size:11px; font-weight:600; }}"
        )


class WorkflowStepBar(QFrame):
    """Горизонтальная панель шагов workflow как в референсе."""

    stageSelected = Signal(str)

    def __init__(
        self,
        on_select: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._tabs: dict[str, WorkflowStepTab] = {}
        self.setObjectName("workflowStepBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(0)
        for index, (stage_id, label, icon_kind) in enumerate(WORKFLOW_TABS):
            if index > 0:
                row.addWidget(WorkflowStepConnector())
            tab = WorkflowStepTab(stage_id, label, icon_kind, self)
            tab.clicked.connect(self._on_select)
            self._tabs[stage_id] = tab
            row.addWidget(tab)
        row.addStretch(1)
        self.setStyleSheet(
            "#workflowStepBar {"
            "background:#060b13; border:1px solid #1a2740; border-radius:10px;"
            "}"
        )

    def set_active_stage(self, stage_id: str) -> None:
        if stage_id not in self._tabs:
            return
        for sid, tab in self._tabs.items():
            tab.set_active(sid == stage_id)


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
        self._plan_step_cards: dict[str, PlanStepRow] = {}
        self._workflow_step_bar: WorkflowStepBar | None = None
        self._launch_stop_action = None
        self._cancel_event = Event()
        self._paused_agent: AgentSpec | None = None
        self._paused_state: object | None = None
        self._human_radios: list[tuple[QRadioButton, str | None]] = []
        self._attachment_paths: list[str] = []
        self._model_options: list[UiModelOption] = []

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
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setHandleWidth(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

    def _build_center(self) -> QWidget:
        """Центральная рабочая область в стиле run timeline из референса."""
        container = QWidget(self)
        container.setObjectName("centerArea")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 16, 8, 14)
        layout.setSpacing(10)

        timeline_panel = QFrame()
        timeline_panel.setObjectName("timelinePanel")
        panel_layout = QVBoxLayout(timeline_panel)
        panel_layout.setContentsMargins(14, 12, 14, 10)
        panel_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title = QLabel("Ход работы агента")
        title.setObjectName("screenTitle")
        self.run_status_badge = QLabel("● Выполняется")
        self.run_status_badge.setObjectName("runStatusBadge")
        title_row.addWidget(title)
        title_row.addWidget(self.run_status_badge)
        title_row.addStretch(1)
        panel_layout.addLayout(title_row)

        summary = QHBoxLayout()
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(18)
        summary.addWidget(self._metric_chip("⏱", "00:01:42", "Прошло"))
        summary.addWidget(self._metric_chip("↱", "Шаг 2 из 6", "Найти поручения в 1С"))
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 100)
        self.run_progress.setValue(33)
        self.run_progress.setTextVisible(False)
        self.run_progress.setFixedHeight(6)
        self.run_progress.setObjectName("runProgress")
        summary.addWidget(self.run_progress, 1, Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(QLabel("33%"))
        summary.addWidget(self._metric_chip("◷", "~2 мин", "Ожидаемое завершение"))
        panel_layout.addLayout(summary)

        self._build_stage_cards()

        self.live_log = LiveLogView()
        self.live_log.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.live_log.setPlaceholderText(
            "Live-события агента появятся здесь: планирование, инструменты, проверки."
        )
        panel_layout.addWidget(self.live_log, 1)

        self._human_panel = self._build_human_panel()
        self._human_panel.setVisible(False)
        panel_layout.addWidget(self._human_panel)

        self.files_label = QLabel()
        self.files_label.setTextFormat(Qt.TextFormat.RichText)
        self.files_label.setOpenExternalLinks(False)
        self.files_label.setWordWrap(True)
        self.files_label.setVisible(False)
        self.files_label.setStyleSheet("color:#8ec3ff; font-size:12px; padding:2px 0;")
        self.files_label.linkActivated.connect(open_local_path)
        panel_layout.addWidget(self.files_label)

        layout.addWidget(timeline_panel, 1)
        layout.addWidget(self._build_bottom_composer(), 0)

        container.setStyleSheet(
            "#centerArea {"
            f"background:{REF_BG};"
            "}"
            "#timelinePanel {"
            f"background:{REF_PANEL}; border:1px solid {REF_BORDER};"
            "border-radius:14px;"
            "}"
            "#screenTitle { color:#f4f8ff; font-size:18px; font-weight:800; }"
            "#runStatusBadge {"
            "background:#0d3a2b; color:#9fffd0; border:1px solid #1c664a;"
            "border-radius:9px; padding:3px 9px; font-size:10px; font-weight:800;"
            "}"
            "#runProgress { background:#17243a; border:none; border-radius:3px; }"
            "#runProgress::chunk { background:#2f7cff; border-radius:3px; }"
            "#metricChip { background:transparent; }"
            "#metricValue { color:#e7eefc; font-size:12px; font-weight:800; }"
            "#metricLabel { color:#667891; font-size:10px; }"
            "QLabel { color:#8da0b8; }"
        )
        return container

    def _metric_chip(self, icon: str, value: str, label: str) -> QWidget:
        chip = QWidget()
        chip.setObjectName("metricChip")
        row = QHBoxLayout(chip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("color:#8daeff; font-size:18px;")
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        texts.addWidget(value_label)
        texts.addWidget(label_widget)
        row.addWidget(icon_label)
        row.addLayout(texts)
        return chip

    def _build_bottom_composer(self) -> QFrame:
        composer = QFrame()
        composer.setObjectName("composerPanel")
        layout = QVBoxLayout(composer)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(5)

        self.request_edit = QTextEdit()
        self.request_edit.setPlaceholderText(EXAMPLE_REQUEST)
        self.request_edit.setFixedHeight(22)
        self.request_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.request_edit.document().setDocumentMargin(0)
        self.request_edit.setObjectName("requestEdit")
        layout.addWidget(self.request_edit)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.attach_button = ComposerIconButton("attach", "Прикрепить файл")
        self.attach_button.clicked.connect(self.attach_files)
        toolbar.addWidget(self.attach_button)
        for kind, tip in (
            ("database", "Источники данных"),
            ("grid", "Табличные данные"),
            ("code", "Параметры JSON"),
        ):
            toolbar.addWidget(ComposerIconButton(kind, tip))

        self._init_model_controls()
        toolbar.addSpacing(4)
        toolbar.addWidget(self.model_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self.reason_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self.refresh_models_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.attach_clear_button = QPushButton("Очистить вложения")
        self.attach_clear_button.clicked.connect(self.clear_attachments)
        self.attach_label = QLabel("Файлы не прикреплены")
        self.attach_clear_button.setVisible(False)
        self.attach_label.setVisible(False)

        toolbar.addStretch(1)
        toolbar.addWidget(self._build_launch_split())
        layout.addLayout(toolbar)

        self._workflow_step_bar = WorkflowStepBar(self.select_stage, composer)
        layout.addWidget(self._workflow_step_bar)

        composer.setStyleSheet(
            "#composerPanel {"
            f"background:{REF_PANEL}; border:1px solid {REF_BORDER};"
            "border-radius:14px;"
            "}"
            "#requestEdit {"
            "background:transparent; color:#cbd5e1; border:none;"
            "padding:0; margin:0; font-size:13px; line-height:1.2;"
            "selection-background-color:#2f7cff;"
            "}"
            "#composerIconButton {"
            "background:#0c1828; color:#94a3b8; border:1px solid #1a2a40;"
            "border-radius:7px;"
            "}"
            "#composerIconButton:hover { background:#132238; border-color:#2a4060; }"
            "#launchSplit { background:#2f80ff; border-radius:9px; }"
            "#launchSplitMain {"
            "background:transparent; color:#ffffff; border:none;"
            "padding:4px 10px; font-size:12px; font-weight:700;"
            "}"
            "#launchSplitMain:hover { background:rgba(255,255,255,0.06); }"
            "#launchSplitMain:disabled { color:#b8ccf5; }"
            "#launchSplitMenu {"
            "background:transparent; color:#ffffff; border:none;"
            "border-left:1px solid #69a6ff; border-top-right-radius:9px;"
            "border-bottom-right-radius:9px; font-size:12px; font-weight:700;"
            "}"
            "#launchSplitMenu:hover { background:rgba(255,255,255,0.08); }"
            "#launchSplitStop {"
            "background:#5a2630; color:#ffc4ce; border:1px solid #8b3342;"
            "border-radius:7px; padding:8px 12px; font-size:12px; font-weight:700;"
            "}"
        )
        return composer

    def _init_model_controls(self) -> None:
        """Создать селекты модели и кнопку обновления для строки toolbar."""
        self.model_combo = BadgeSelect(ghost=False)
        self.model_combo.setObjectName("modelCombo")
        self._configure_compact_combo(self.model_combo)

        self.reason_combo = BadgeSelect(ghost=True)
        self.reason_combo.setObjectName("reasonCombo")
        self._configure_compact_combo(self.reason_combo)
        self.reason_combo.addItem("internal", "internal")
        self.reason_combo.addItem("reason", "reason")

        self.refresh_models_button = QPushButton("Обновить")
        self.refresh_models_button.setObjectName("modelRefreshButton")
        self.refresh_models_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_models_button.setFixedHeight(22)
        self.refresh_models_button.setStyleSheet(MODEL_REFRESH_BUTTON_STYLE)
        self._reload_model_options()

    def _configure_compact_combo(self, combo: BadgeSelect) -> None:
        """Настроить pill-селект под ширину текущего значения."""
        combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        combo.setFixedHeight(22)

    def _fit_combo_to_contents(self, combo: BadgeSelect) -> None:
        """Подогнать ширину селекта под текущий выбранный пункт."""
        text = combo.currentText()
        if not text:
            return
        metrics = combo.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        combo.setFixedWidth(text_width + 34)

    def _build_launch_split(self) -> QWidget:
        """Split-кнопка «Запустить агента» с выпадающим меню, как в референсе."""
        self.create_button = QPushButton("Запустить агента")
        self.save_button = QPushButton("Сохранить")
        self.reset_button = QPushButton("Сбросить")
        self.stop_button = QPushButton("Остановить")
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)

        self._action_buttons = [
            self.create_button,
            self.save_button,
            self.reset_button,
        ]

        wrap = QFrame()
        wrap.setObjectName("launchSplit")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.create_button.setObjectName("launchSplitMain")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.create_button)

        menu_button = QPushButton("▾")
        menu_button.setObjectName("launchSplitMenu")
        menu_button.setFixedSize(28, 28)
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)

        menu = QMenu(wrap)
        menu.setStyleSheet(
            "QMenu { background:#0f172a; color:#dbeafe; border:1px solid #1e3a5f; "
            "padding:4px; }"
            "QMenu::item { padding:6px 14px; border-radius:4px; }"
            "QMenu::item:selected { background:#1d4ed8; }"
        )
        menu.addAction("Сохранить агента", self.save_agent)
        menu.addAction("Сбросить форму", self.clear)
        menu.addAction("Очистить вложения", self.clear_attachments)
        menu.addSeparator()
        stop_action = menu.addAction("Остановить выполнение", self.request_stop)
        stop_action.setEnabled(False)
        self._launch_stop_action = stop_action
        menu_button.setMenu(menu)
        row.addWidget(menu_button)

        host = QHBoxLayout()
        host.setContentsMargins(0, 0, 0, 0)
        host.setSpacing(8)
        host.addWidget(wrap)
        self.stop_button.setObjectName("launchSplitStop")
        host.addWidget(self.stop_button)
        container = QWidget()
        container.setLayout(host)
        return container

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
        """Создать скрытые карточки стадий для логики статусов без ленты в центре."""
        last_index = len(STAGE_ORDER)
        for index, (stage_id, title, subtitle) in enumerate(STAGE_ORDER, start=1):
            card = StageCard(
                index,
                stage_id,
                title,
                subtitle,
                index == last_index,
                self.select_stage,
                parent=self,
            )
            card.hide()
            self._stage_cards[stage_id] = card

    def _build_details_panel(self) -> QWidget:
        """Правая панель плана и текущего шага как на референсе."""
        panel = QWidget()
        panel.setObjectName("detailsPanel")
        panel.setMinimumWidth(318)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 16, 14, 14)
        layout.setSpacing(12)

        plan_panel = QFrame()
        plan_panel.setObjectName("planPanel")
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(16, 16, 16, 14)
        plan_layout.setSpacing(12)
        header = QLabel("План")
        header.setObjectName("planTitle")
        plan_layout.addWidget(header)

        self._plan_steps_list = PlanStepsList(self)
        for index, (stage_id, title, _subtitle) in enumerate(STAGE_ORDER[:6], start=1):
            row = PlanStepRow(index, stage_id, title, self)
            self._plan_step_cards[stage_id] = row
            self._plan_steps_list.add_step(row)
        plan_layout.addWidget(self._plan_steps_list)
        plan_layout.addStretch(1)
        layout.addWidget(plan_panel, 2)

        current_panel = QFrame()
        current_panel.setObjectName("sidePanel")
        current_layout = QVBoxLayout(current_panel)
        current_layout.setContentsMargins(14, 14, 14, 14)
        current_layout.setSpacing(10)
        current_header = QLabel("Текущий шаг")
        current_header.setObjectName("sideTitle")
        current_layout.addWidget(current_header)

        self.current_step_card = QFrame()
        self.current_step_card.setObjectName("currentStepCard")
        current_card_layout = QVBoxLayout(self.current_step_card)
        current_card_layout.setContentsMargins(12, 10, 12, 10)
        current_card_layout.setSpacing(6)

        self.detail_title = QLabel("Запрос пользователя")
        self.detail_title.setObjectName("currentStepTitle")
        self.detail_title.setWordWrap(True)
        current_card_layout.addWidget(self.detail_title)

        self.detail_status = QLabel()
        self.detail_status.setObjectName("currentStepStatus")
        current_card_layout.addWidget(self.detail_status)
        current_layout.addWidget(self.current_step_card)

        eta = QLabel("◷  Ожидаемое завершение ~2 мин")
        eta.setObjectName("etaLabel")
        current_layout.addWidget(eta)

        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setObjectName("detailView")
        current_layout.addWidget(self.detail_view, 1)
        layout.addWidget(current_panel, 2)

        self.dev_toggle = QPushButton("▸ Для разработчика (JSON и таблицы)")
        self.dev_toggle.setCheckable(True)
        self.dev_toggle.setObjectName("devToggle")
        self.dev_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.dev_toggle)

        self._dev_container = self._build_dev_tabs()
        self._dev_container.setVisible(False)
        layout.addWidget(self._dev_container, 1)

        panel.setStyleSheet(
            "#detailsPanel {"
            f"background:{REF_BG}; border-left:1px solid #10243c;"
            "}"
            "#planPanel, #sidePanel {"
            f"background:{REF_PANEL}; border:1px solid {REF_BORDER};"
            "border-radius:14px;"
            "}"
            "#planTitle, #sideTitle { color:#f4f8ff; font-size:18px; font-weight:800; }"
            "#currentStepCard { background:#0d213b; border:1px solid #183e68; border-radius:12px; }"
            "#currentStepTitle { color:#e7eefc; font-size:13px; font-weight:800; }"
            "#currentStepStatus { color:#9eb5d4; font-size:11px; }"
            "#etaLabel { color:#75869f; font-size:11px; padding:4px 0; }"
            "#detailView {"
            "background:#071426; color:#aebbd0; border:1px solid #102844;"
            "border-radius:10px; padding:10px; font-size:11px;"
            "selection-background-color:#2f7cff;"
            "}"
            "#devToggle {"
            "text-align:left; background:#0a1a2e; color:#8fa1bd;"
            "border:1px solid #122844; border-radius:10px; padding:8px 10px;"
            "font-size:11px; font-weight:700;"
            "}"
            "#devToggle:hover { color:#d7e3f8; border-color:#2f7cff; }"
            "#devToggle:checked { color:#e8f0ff; background:#102946; }"
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
        self.refresh_models_button.clicked.connect(self._reload_model_options)
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        self.reason_combo.currentIndexChanged.connect(
            lambda _index: self._fit_combo_to_contents(self.reason_combo)
        )

    def _toggle_dev(self, checked: bool) -> None:
        """Показать или скрыть раздел разработчика."""
        self._dev_container.setVisible(checked)
        arrow = "▾" if checked else "▸"
        self.dev_toggle.setText(f"{arrow} Для разработчика (JSON и таблицы)")

    def _reload_model_options(self) -> None:
        """Загрузить модели для селекта из LLM-прокси или из текущих настроек."""
        config = getattr(self._container, "config", None)
        current_model = getattr(config, "llm_model_name", "chatgpt:internal")
        options = _merge_default_model_options(self._load_proxy_model_options())
        self._model_options = options
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for option in options:
            self.model_combo.addItem(option.label, option.model_id)
        base_model, mode = _split_model_mode(current_model)
        selected_index = 0
        for index, option in enumerate(options):
            if option.model_id == base_model or option.model_id == current_model:
                selected_index = index
                break
        self.model_combo.setCurrentIndex(selected_index)
        self.model_combo.blockSignals(False)
        self._sync_reason_combo()
        self._fit_combo_to_contents(self.model_combo)
        self._fit_combo_to_contents(self.reason_combo)
        if mode:
            reason_index = self.reason_combo.findData(mode)
            if reason_index >= 0:
                self.reason_combo.setCurrentIndex(reason_index)

    def _load_proxy_model_options(self) -> list[UiModelOption]:
        """Получить модели через /v1/models, если настроен LLM proxy URL."""
        config = getattr(self._container, "config", None)
        proxy_url = (getattr(config, "llm_proxy_url", None) or "").strip()
        if not proxy_url:
            return []
        url = proxy_url.rstrip("/") + "/v1/models"
        try:
            with request.urlopen(url, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, error.URLError):
            return []
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []

        by_base: dict[str, dict] = {}
        order: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            base_model, mode = _split_model_mode(model_id)
            if base_model not in {"chatgpt", "lmstudio"}:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            entry = by_base.setdefault(
                base_model,
                {
                    "label": metadata.get("display_name") or base_model,
                    "supports_reasoning": bool(metadata.get("supports_reasoning")),
                    "modes": set(),
                },
            )
            if base_model not in order:
                order.append(base_model)
            if mode:
                entry["modes"].add(mode)

        options: list[UiModelOption] = []
        for base_model in order:
            entry = by_base[base_model]
            modes = tuple(mode for mode in ("internal", "reason") if mode in entry["modes"])
            options.append(
                UiModelOption(
                    model_id=base_model,
                    label=str(entry["label"]),
                    supports_reasoning=bool(entry["supports_reasoning"]) or bool(modes),
                    modes=modes,
                )
            )
        return options

    def _current_model_option(self) -> UiModelOption | None:
        """Вернуть выбранную base-модель."""
        index = self.model_combo.currentIndex()
        if index < 0 or index >= len(self._model_options):
            return None
        return self._model_options[index]

    def _on_model_combo_changed(self, _index: int) -> None:
        """Обновить reason-селект и ширину pill-комбобоксов после смены модели."""
        self._sync_reason_combo()
        self._fit_combo_to_contents(self.model_combo)

    def _sync_reason_combo(self) -> None:
        """Включить/выключить селект reason в зависимости от выбранной модели."""
        option = self._current_model_option()
        supports = bool(option and option.supports_reasoning)
        self.reason_combo.setEnabled(supports)
        if not supports:
            self.reason_combo.setToolTip("Эта модель не объявила поддержку reason.")
            self._fit_combo_to_contents(self.reason_combo)
            return
        self.reason_combo.setToolTip("Режим reasoning для выбранной модели.")
        mode = self.reason_combo.currentData()
        allowed = set(option.modes or ("internal", "reason"))
        if mode not in allowed:
            self.reason_combo.setCurrentIndex(0)
        self._fit_combo_to_contents(self.reason_combo)

    def _selected_model_id(self) -> str:
        """Сформировать model id для LLM config из селектов UI."""
        option = self._current_model_option()
        if option is None:
            config = getattr(self._container, "config", None)
            return getattr(config, "llm_model_name", "chatgpt:internal")
        if option.supports_reasoning:
            mode = str(self.reason_combo.currentData() or "internal")
            return f"{option.model_id}:{mode}"
        return option.model_id

    def _ensure_selected_model_container(self) -> None:
        """Пересобрать container, если в UI выбрана другая LLM-модель."""
        config = getattr(self._container, "config", None)
        if config is None:
            return
        selected_model = self._selected_model_id()
        if selected_model == config.llm_model_name:
            return
        self._append_log(f"⚙ Переключаю LLM-модель на {selected_model}…")
        new_config = config.model_copy(
            update={"llm_model_name": selected_model}
        )
        self._container = build_application_container(new_config)
        self._preview_agent = None

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
        self.stop_button.setVisible(True)
        if self._launch_stop_action is not None:
            self._launch_stop_action.setEnabled(True)
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
        self.stop_button.setVisible(False)
        if self._launch_stop_action is not None:
            self._launch_stop_action.setEnabled(False)
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
        self._ensure_selected_model_container()
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
        self._ensure_selected_model_container()
        existing_spec = self._preview_agent
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
        self._ensure_selected_model_container()
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

        self._ensure_selected_model_container()
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
        """Обновить подсказку на кнопке вложений."""
        if not self._attachment_paths:
            self.attach_button.setToolTip("Прикрепить файл")
            return
        from pathlib import Path

        names = ", ".join(Path(path).name for path in self._attachment_paths)
        self.attach_button.setToolTip(f"Прикреплено: {names}")
        if self.attach_label is not None:
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
            if stage_id in self._plan_step_cards:
                self._plan_step_cards[stage_id].set_status("pending")
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
        if stage_id in self._plan_step_cards:
            self._plan_step_cards[stage_id].set_status(status)
        self._stage_details[stage_id] = detail
        if self._selected_stage == stage_id:
            self.select_stage(stage_id)

    def _set_running(self, stage_id: str) -> None:
        """Пометить стадию как выполняющуюся."""
        self._stage_cards[stage_id].set_status("running")
        if stage_id in self._plan_step_cards:
            self._plan_step_cards[stage_id].set_status("running")

    def select_stage(self, stage_id: str) -> None:
        """Показать детали выбранной стадии в правой панели."""
        self._selected_stage = stage_id
        for other_id, card in self._stage_cards.items():
            card.set_selected(other_id == stage_id)
        for other_id, card in self._plan_step_cards.items():
            card.set_active(other_id == stage_id)
        if self._workflow_step_bar is not None:
            self._workflow_step_bar.set_active_stage(stage_id)
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
