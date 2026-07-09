"""Страница создания агента в стиле пошагового workflow.

UI-слой не меняет внутреннюю логику конструктора: используются те же вызовы
``agent_service`` (build_preview / validate_agent / create_validate_and_run_once /
save_agent / create_agent_from_request). Экран лишь показывает наглядно, что агент
построил, что проверяет, что запускает и почему что-то не сработало.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
from urllib import error, request

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    Property,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtSvg import QSvgRenderer
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
from agent_desktop_constructor.app.core.settings import save_llm_model_name
from agent_desktop_constructor.app.ui.widgets.context_indicator import ContextIndicator
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
    UiModelOption(
        "lmstudio",
        "LM Studio (gpt-oss-120b)",
        supports_reasoning=True,
        modes=("internal", "reason"),
    ),
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
    """Гарантировать базовые модели и добавить discovery-модели из прокси."""
    merged: dict[str, UiModelOption] = {
        option.model_id: option for option in DEFAULT_UI_MODEL_OPTIONS
    }
    order = ["chatgpt", "lmstudio"]
    for option in options:
        if option.model_id not in merged:
            order.append(option.model_id)
        merged[option.model_id] = option
    return [merged[model_id] for model_id in order if model_id in merged]

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

TRACKED_STAGE_IDS: tuple[str, ...] = tuple(stage_id for stage_id, _, _ in WORKFLOW_TABS)
WORKFLOW_STAGE_LABELS: dict[str, str] = {
    stage_id: label for stage_id, label, _ in WORKFLOW_TABS
}

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

COMPOSER_ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
COMPOSER_ICON_FILES: dict[str, tuple[str, str]] = {
    "attach": ("paperclip-default.svg", "paperclip-active.svg"),
    "database": ("server-default.svg", "server-active.svg"),
}


def _short(text: object, max_len: int = 90) -> str:
    """Короткая однострочная подпись для карточки."""
    value = " ".join(str(text or "").split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def _format_elapsed_seconds(seconds: float) -> str:
    """Отформатировать elapsed time как HH:MM:SS."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


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


class CursorLiveText(QLabel):
    """Строка live-лога: shimmer для действий и typewriter для комментариев."""

    def __init__(
        self,
        text: str,
        *,
        color: str,
        shimmer: bool = False,
        typewriter: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = text
        self._visible_chars = 0 if typewriter else len(text)
        self._base_color = QColor(color)
        self._shimmer = shimmer
        self._shimmer_offset = -0.35
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setStyleSheet(f"background:transparent; color:{color}; font-size:12px;")
        self.setText(text if not typewriter else "")

        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(13)
        self._typing_timer.timeout.connect(self._type_next_chunk)
        if typewriter:
            self._typing_timer.start()

        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setInterval(48)
        self._shimmer_timer.timeout.connect(self._advance_shimmer)
        if shimmer:
            self._shimmer_timer.start()

    def _type_next_chunk(self) -> None:
        if self._visible_chars >= len(self._full_text):
            self._typing_timer.stop()
            return
        chunk = 3 if len(self._full_text) > 90 else 2
        self._visible_chars = min(len(self._full_text), self._visible_chars + chunk)
        self.setText(self._full_text[: self._visible_chars])
        self.updateGeometry()

    def _advance_shimmer(self) -> None:
        self._shimmer_offset += 0.009
        if self._shimmer_offset > 1.35:
            self._shimmer_offset = -0.35
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._shimmer or not self.text():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        text_rect = self.contentsRect()
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap

        painter.setPen(self._base_color)
        painter.drawText(text_rect, int(flags), self.text())

        band_width = max(52, int(self.width() * 0.3))
        center_x = int(self.width() * self._shimmer_offset)
        painter.save()
        painter.setClipRect(text_rect)
        for spread, alpha in ((-0.22, 28), (0.0, 78), (0.22, 28)):
            half = int(band_width * 0.38)
            x = center_x + int(band_width * spread) - half
            painter.save()
            painter.setClipRect(
                QRect(x, 0, half * 2, self.height()),
                Qt.ClipOperation.IntersectClip,
            )
            painter.setPen(QColor(232, 241, 255, alpha))
            painter.drawText(text_rect, int(flags), self.text())
            painter.restore()
        painter.restore()


class LiveLogView(QScrollArea):
    """Cursor-like поток live-событий без карточек."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Создать прокручиваемую ленту событий агента."""
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._animations: list[QPropertyAnimation] = []

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("liveLogView")

        self._host = QWidget()
        self._host.setObjectName("liveLogHost")
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)

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
            "#liveLogView { background:transparent; border:none; }"
            "#liveLogHost { background:transparent; }"
            "#livePlaceholder { color:#66738b; font-size:12px; padding:8px; }"
            "#liveLogRow { background:transparent; border:none; }"
            "#liveLogIcon { color:#9bbcff; font-size:13px; font-weight:700; }"
            "#liveLogText { background:transparent; }"
        )

    def setReadOnly(self, _read_only: bool) -> None:  # noqa: N802 (Qt compatibility)
        """Совместимость с QTextEdit API."""

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 (Qt compatibility)
        """Совместимость с QTextEdit API."""
        self._placeholder.setText(text)

    def append(self, message: str) -> None:
        """Добавить событие в Cursor-like поток с анимацией по типу сообщения."""
        text = str(message or "").strip()
        if not text:
            return
        self._placeholder.setVisible(False)

        row = QWidget()
        row.setObjectName("liveLogRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        icon = QLabel(self._event_icon(text))
        icon.setObjectName("liveLogIcon")
        icon.setFixedWidth(14)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        icon.setStyleSheet(f"color:{self._accent_color(text)};")
        row_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        body = CursorLiveText(
            self._clean_message(text),
            color=self._text_color(text),
            shimmer=self._is_running_action(text),
            typewriter=self._is_typewriter_message(text),
        )
        body.setObjectName("liveLogText")
        row_layout.addWidget(body, 1)

        self._layout.insertWidget(max(0, self._layout.count() - 1), row)
        self._items.append(row)
        if len(self._items) > 120:
            old = self._items.pop(0)
            old.setParent(None)
            old.deleteLater()
        self._fade_in(row)
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
        animation.setDuration(180)
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

    def _event_icon(self, text: str) -> str:
        if text.startswith("✅"):
            return "✓"
        if text.startswith("⚠") or text.startswith("❌"):
            return "!"
        if text.startswith("⏸"):
            return "Ⅱ"
        if text.startswith("📎"):
            return "↗"
        if text.startswith("⏹"):
            return "■"
        return "✦" if self._is_running_action(text) else "•"

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

    def _text_color(self, text: str) -> str:
        if text.startswith("⚠") or text.startswith("❌"):
            return "#f2c7d0"
        if text.startswith("✅"):
            return "#c8f8df"
        return "#b9c7dd" if self._is_running_action(text) else "#8fa1bb"

    def _is_running_action(self, text: str) -> bool:
        lower = text.lower()
        return (
            text.startswith(("🧩", "🔎", "▶", "⚙"))
            or "строю" in lower
            or "переключаю" in lower
            or "запускаю" in lower
            or "проверяю" in lower
        )

    def _is_typewriter_message(self, text: str) -> bool:
        lower = text.lower()
        return (
            text.startswith(("⚠", "❌"))
            or "не удалось" in lower
            or "ошибка" in lower
            or "причина:" in lower
        )

    @staticmethod
    def _clean_message(text: str) -> str:
        return text.lstrip("✅⚠❌⏸📎🧩🔎▶⏹⚙ ").strip() or text


class PlanNumberCircle(QWidget):
    """Круг с номером шага, как в референсе плана."""

    def __init__(self, number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._number = number
        self._visual = "pending"
        self.setFixedSize(36, 36)

    def set_visual(self, visual: str) -> None:
        self._visual = visual
        self.update()

    def set_number(self, number: int) -> None:
        self._number = number
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(2, 2, 32, 32)
        if self._visual == "active":
            border = QColor("#3b82f6")
            text = QColor("#eef5ff")
        elif self._visual == "passed":
            border = QColor("#4b5568")
            text = QColor("#9aa8bc")
        else:
            border = QColor("#334155")
            text = QColor("#64748b")
        pen = QPen(border, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)
        number_font = QFont("Segoe UI", 11, QFont.Weight.Bold)
        painter.setFont(number_font)
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


class CurrentStepCard(QFrame):
    """Карточка текущего шага в правом сайдбаре."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("currentStepCard")

        self._number = PlanNumberCircle(1)

        self._title = QLabel("Запрос пользователя")
        self._title.setObjectName("currentStepCardTitle")
        self._title.setWordWrap(True)

        self._detail = QLabel("Ожидает начала")
        self._detail.setObjectName("currentStepCardDetail")
        self._detail.setWordWrap(True)

        self._status_dot = PlanStatusIcon()

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(4)
        texts.addWidget(self._title)
        texts.addWidget(self._detail)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        row.addWidget(self._number, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(texts, 1)
        row.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_content(1, "Запрос пользователя", "Ожидает начала", "pending")

    def set_content(
        self,
        index: int,
        title: str,
        detail: str,
        status: str,
    ) -> None:
        self._number.set_number(index)
        self._title.setText(title)
        self._detail.setText(detail)
        is_running = status == "running"
        is_passed = status == "passed"
        is_pending = status == "pending"
        is_problem = status in {
            "failed",
            "warning",
            "needs_human",
            "needs_credentials",
        }

        if is_running:
            card_bg = "#0f2340"
            card_border = "#3b82f6"
            number_visual = "active"
            title_color = "#eef5ff"
            detail_color = "#7f8ea5"
            self._status_dot.set_mode("dot")
        elif is_passed:
            card_bg = "rgba(21, 26, 35, 0.72)"
            card_border = "#334155"
            number_visual = "passed"
            title_color = "#dbe4f2"
            detail_color = "#7f8ea5"
            self._status_dot.set_mode("check")
        elif is_problem:
            card_bg = "rgba(21, 26, 35, 0.72)"
            card_border = "#334155"
            number_visual = "pending"
            title_color = "#f87171" if status == "failed" else "#fbbf24"
            detail_color = "#7f8ea5"
            self._status_dot.set_mode("none")
        elif is_pending:
            card_bg = "#0f2340"
            card_border = "#3b82f6"
            number_visual = "active"
            title_color = "#eef5ff"
            detail_color = "#7f8ea5"
            self._status_dot.set_mode("none")
        else:
            card_bg = "rgba(21, 26, 35, 0.55)"
            card_border = "#1e3a5f"
            number_visual = "pending"
            title_color = "#cbd5e1"
            detail_color = "#7f8ea5"
            self._status_dot.set_mode("none")

        self._number.set_visual(number_visual)
        self.setStyleSheet(
            "#currentStepCard {"
            f"background:{card_bg}; border:1px solid {card_border};"
            "border-radius:14px;"
            "}"
            f"#currentStepCardTitle {{ color:{title_color}; font-size:14px; font-weight:700; }}"
            f"#currentStepCardDetail {{ color:{detail_color}; font-size:11px; }}"
        )


class PlanStepRow(QFrame):
    """Строка шага в блоке «План» с рамкой у активного этапа."""

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
        self.setMinimumHeight(54)
        self.setMaximumHeight(72)

        self._number = PlanNumberCircle(index)
        self._title = QLabel(title)
        self._title.setObjectName("planStepTitle")
        self._title.setWordWrap(True)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._status_icon = PlanStatusIcon()

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
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
            row_bg = "#0f2340"
            title_color = "#eef5ff"
            number_visual = "active"
            status_mode = "dot"
            border = "1px solid #3b82f6"
        elif is_passed:
            row_bg = "rgba(21, 26, 35, 0.72)"
            title_color = "#b8c5d6"
            number_visual = "passed"
            status_mode = "check"
            border = "1px solid transparent"
        elif is_problem:
            row_bg = "rgba(21, 26, 35, 0.72)"
            title_color = "#fbbf24" if self._status != "failed" else "#f87171"
            number_visual = "pending"
            status_mode = "none"
            border = "1px solid transparent"
        elif self._active:
            row_bg = "#0f2340"
            title_color = "#eef5ff"
            number_visual = "active"
            status_mode = "none"
            border = "1px solid #3b82f6"
        else:
            row_bg = "transparent"
            title_color = "#64748b"
            number_visual = "pending"
            status_mode = "none"
            border = "1px solid transparent"

        self._number.set_visual(number_visual)
        self._status_icon.set_mode(status_mode)
        self.setStyleSheet(
            "#planStepRow {"
            f"background:{row_bg}; border:{border}; border-radius:10px;"
            "}"
            "#planStepRow:hover { background:#172338; }"
            f"#planStepTitle {{ color:{title_color}; font-size:14px; font-weight:600; }}"
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
        self._layout.setSpacing(8)

    def add_step(self, row: PlanStepRow) -> None:
        self._rows.append(row)
        self._layout.addWidget(row)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if len(self._rows) < 2:
            return
        painter = QPainter(self)
        # Без Antialiasing: пунктирная линия дешёвая и не даёт лагов при resize.
        pen = QPen(QColor("#2563eb"), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([2.5, 3.5])
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        # Фиксированный x по первому кругу — без mapTo на каждый resize/paint.
        first_number = self._rows[0]._number
        x = first_number.x() + first_number.width() / 2
        radius = 16.0
        for index in range(len(self._rows) - 1):
            top_row = self._rows[index]
            bottom_row = self._rows[index + 1]
            start_y = top_row.y() + top_row._number.y() + top_row._number.height() / 2 + radius
            end_y = (
                bottom_row.y()
                + bottom_row._number.y()
                + bottom_row._number.height() / 2
                - radius
            )
            if end_y > start_y:
                painter.drawLine(QPointF(x, start_y), QPointF(x, end_y))


class LaunchSplitMenuButton(QPushButton):
    """Правая часть split-кнопки: шеврон без системного menu-indicator Qt."""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#ffffff" if self.isEnabled() else "#b8ccf5")
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center_x = self.width() / 2
        center_y = self.height() / 2 + 0.5
        path = QPainterPath()
        path.moveTo(center_x - 3.4, center_y - 1.4)
        path.lineTo(center_x, center_y + 2.0)
        path.lineTo(center_x + 3.4, center_y - 1.4)
        painter.drawPath(path)


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
        self._block_open_until = 0.0
        self._menu.aboutToHide.connect(self._on_menu_about_to_hide)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._open_menu)
        self._apply_style()

    def _on_menu_about_to_hide(self) -> None:
        """Не переоткрывать меню сразу после закрытия тем же кликом по кнопке."""
        self._block_open_until = time.monotonic() + 0.3

    def _apply_style(self) -> None:
        self.setStyleSheet(REASON_BADGE_STYLE if self._ghost else MODEL_BADGE_STYLE)

    def _chevron_color(self) -> QColor:
        if not self.isEnabled():
            return QColor("#475569" if self._ghost else "#5c6b82")
        if self.underMouse():
            return QColor("#9da9bf" if self._ghost else "#c5d0e4")
        return QColor("#94a3b8" if self._ghost else "#9da9bf")

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._chevron_color(), 1.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center_x = self.width() - 11
        center_y = self.height() / 2
        path = QPainterPath()
        path.moveTo(center_x - 3.2, center_y - 1.8)
        path.lineTo(center_x, center_y + 1.6)
        path.lineTo(center_x + 3.2, center_y - 1.8)
        painter.drawPath(path)

    def _open_menu(self) -> None:
        if time.monotonic() < self._block_open_until:
            return
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
        self.setText(self._labels[index])
        if emit and previous != index:
            self.currentIndexChanged.emit(index)


class ComposerIconButton(QPushButton):
    """Квадратная кнопка с SVG-иконкой для нижней панели composer."""

    _ICON_SIZE = 18
    _svg_cache: dict[str, tuple[QSvgRenderer, QSvgRenderer]] = {}

    def __init__(self, kind: str, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setText("")
        self.setObjectName("composerIconButton")
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(30, 30)

    @classmethod
    def _svg_renderers(cls, kind: str) -> tuple[QSvgRenderer, QSvgRenderer] | None:
        files = COMPOSER_ICON_FILES.get(kind)
        if files is None:
            return None
        if kind not in cls._svg_cache:
            default_path = COMPOSER_ICONS_DIR / files[0]
            active_path = COMPOSER_ICONS_DIR / files[1]
            cls._svg_cache[kind] = (
                QSvgRenderer(str(default_path)),
                QSvgRenderer(str(active_path)),
            )
        return cls._svg_cache[kind]

    def _use_active_icon(self) -> bool:
        return self.underMouse() or self.isDown()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        renderers = self._svg_renderers(self._kind)
        if renderers is not None:
            renderer = renderers[1] if self._use_active_icon() else renderers[0]
            if renderer.isValid():
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                offset = (self.width() - self._ICON_SIZE) / 2
                renderer.render(
                    painter,
                    QRectF(offset, offset, self._ICON_SIZE, self._ICON_SIZE),
                )
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#94a3b8")
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._kind == "grid":
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


class MetricChipIcon(QWidget):
    """Line-icon для метрик шапки timeline (часы, шаг, ETA)."""

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
        if self._kind == "elapsed":
            painter.drawEllipse(QRectF(3, 3.5, 10, 10))
            painter.drawLine(QPointF(8, 3.5), QPointF(8, 2))
            painter.drawLine(QPointF(6.5, 2), QPointF(9.5, 2))
            painter.drawLine(QPointF(8, 8.5), QPointF(8, 6.2))
            painter.drawLine(QPointF(8, 8.5), QPointF(10.2, 8.5))
        elif self._kind == "step":
            painter.drawLine(QPointF(2.5, 11.5), QPointF(9, 11.5))
            painter.drawLine(QPointF(9, 11.5), QPointF(9, 5))
            painter.drawLine(QPointF(9, 5), QPointF(12.5, 8))
            painter.drawLine(QPointF(9, 5), QPointF(6.5, 8))
        else:
            painter.drawEllipse(QRectF(2.5, 2.5, 11, 11))
            painter.drawLine(QPointF(8, 8), QPointF(8, 5.2))
            painter.drawLine(QPointF(8, 8), QPointF(10.4, 8))


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
        self._launch_stop_action = None
        self._request_min_height = 22
        self._request_max_height = 120
        self._cancel_event = Event()
        self._paused_agent: AgentSpec | None = None
        self._paused_state: object | None = None
        self._human_radios: list[tuple[QRadioButton, str | None]] = []
        self._attachment_paths: list[str] = []
        self._model_options: list[UiModelOption] = []
        self.context_indicator: ContextIndicator | None = None
        self.open_workspace_button: QPushButton | None = None
        self._run_started_at: float | None = None
        self._run_elapsed_seconds = 0.0
        self._run_timer = QTimer(self)
        self._run_timer.setInterval(1000)
        self._run_timer.timeout.connect(self._refresh_run_header)
        self._main_splitter: QSplitter | None = None
        self._resize_sync_timer = QTimer(self)
        self._resize_sync_timer.setSingleShot(True)
        self._resize_sync_timer.setInterval(48)
        self._resize_sync_timer.timeout.connect(self._apply_deferred_resize_sync)
        self._request_height_sync_pending = False

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
        # Центр доминирует; правая колонка узкая и почти не растягивается.
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        self._main_splitter = splitter
        QTimer.singleShot(0, self._apply_default_splitter_sizes)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

    def _apply_default_splitter_sizes(self) -> None:
        """Задать начальные размеры: центр шире, план справа уже."""
        splitter = self._main_splitter
        if splitter is None:
            return
        total = max(splitter.width(), 900)
        right = min(300, max(260, total // 4))
        left = max(total - right, total - 320)
        splitter.setSizes([left, right])

    def _build_center(self) -> QWidget:
        """Центральная рабочая область в стиле run timeline из референса."""
        container = QWidget(self)
        container.setObjectName("centerArea")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 16, 8, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title = QLabel("Ход работы агента")
        title.setObjectName("screenTitle")
        self.run_status_badge = QLabel("○ Ожидает")
        self.run_status_badge.setObjectName("runStatusBadge")
        self.run_status_badge.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.open_workspace_button = QPushButton("Открыть папку агента")
        self.open_workspace_button.setObjectName("workspaceButton")
        self.open_workspace_button.setEnabled(False)
        self.open_workspace_button.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.open_workspace_button.clicked.connect(self.open_agent_workspace)
        title_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.run_status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        title_row.addWidget(
            self.open_workspace_button,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        layout.addLayout(title_row)

        summary = QHBoxLayout()
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(14)
        elapsed_chip, self._elapsed_value_label, _, self._elapsed_icon = self._metric_chip(
            "elapsed", "00:00:00", "Прошло"
        )
        summary.addWidget(elapsed_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        step_chip, self._step_value_label, self._step_detail_label, self._step_icon = (
            self._metric_chip("step", "Шаг 1 из 8", "Ожидает запуска")
        )
        summary.addWidget(step_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        progress_group = QWidget()
        progress_group.setObjectName("runProgressGroup")
        progress_row = QHBoxLayout(progress_group)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 100)
        self.run_progress.setValue(0)
        self.run_progress.setTextVisible(False)
        self.run_progress.setFixedHeight(6)
        self.run_progress.setMinimumWidth(72)
        self.run_progress.setObjectName("runProgress")
        progress_row.addWidget(self.run_progress, 1, Qt.AlignmentFlag.AlignVCenter)
        self._progress_percent_label = QLabel("0%")
        self._progress_percent_label.setObjectName("metricValue")
        self._progress_percent_label.setFixedWidth(34)
        self._progress_percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress_row.addWidget(
            self._progress_percent_label,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        summary.addWidget(progress_group, 1, Qt.AlignmentFlag.AlignVCenter)

        eta_chip, self._eta_header_value_label, _, self._eta_icon = self._metric_chip(
            "eta", "—", "Ожидаемое завершение"
        )
        summary.addWidget(eta_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(summary)

        self._build_stage_cards()

        live_section = QWidget()
        live_section.setObjectName("liveSection")
        panel_layout = QVBoxLayout(live_section)
        panel_layout.setContentsMargins(0, 4, 0, 0)
        panel_layout.setSpacing(10)

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

        layout.addWidget(live_section, 1)
        layout.addWidget(self._build_bottom_composer(), 0)

        container.setStyleSheet(
            "#centerArea {"
            f"background:{REF_BG};"
            "}"
            "#liveSection { background:transparent; }"
            "#screenTitle { color:#f4f8ff; font-size:18px; font-weight:800; }"
            "#runStatusBadge {"
            f"background:{STATUS_STYLE['pending'][1]}; color:{STATUS_STYLE['pending'][2]};"
            "border:1px solid rgba(255,255,255,0.07);"
            "border-radius:9px; padding:3px 9px; font-size:10px; font-weight:700;"
            "margin:0;"
            "}"
            "#workspaceButton {"
            "background:#182338; color:#b9d7ff; border:1px solid #2b4c7a;"
            "border-radius:9px; padding:5px 10px; font-size:11px; font-weight:700;"
            "margin:0;"
            "}"
            "#workspaceButton:disabled { color:#526075; border-color:#263247; }"
            f"#runProgress {{ background:{REF_PANEL_ALT}; border:none; border-radius:3px; }}"
            f"#runProgress::chunk {{ background:{REF_BLUE}; border-radius:3px; }}"
            "#runProgressGroup { background:transparent; }"
            "#metricChip { background:transparent; min-height:28px; }"
            f"#metricValue {{ color:{REF_TEXT}; font-size:12px; font-weight:700; }}"
            f"#metricLabel {{ color:{REF_MUTED}; font-size:10px; font-weight:600; }}"
            "QLabel { color:#8da0b8; }"
        )
        return container

    def _status_badge_stylesheet(self, status_key: str) -> tuple[str, str]:
        """Текст и QSS бейджа статуса в стиле stageBadge / BadgeSelect."""
        label, bg, fg, icon = STATUS_STYLE[status_key]
        display = {
            "pending": "○ Ожидает",
            "running": "● Выполняется",
            "passed": "✓ Завершено",
            "failed": "✕ Ошибка",
            "needs_human": "⏸ Ожидает ответа",
            "needs_credentials": "🔑 Авторизация",
            "warning": f"{icon} {label}",
        }.get(status_key, f"{icon} {label}")
        stylesheet = (
            f"background:{bg}; color:{fg}; border:1px solid rgba(255,255,255,0.07);"
            "border-radius:9px; padding:3px 9px; font-size:10px; font-weight:700;"
        )
        return display, stylesheet

    def _metric_chip(
        self,
        icon_kind: str,
        value: str,
        label: str,
    ) -> tuple[QWidget, QLabel, QLabel, MetricChipIcon]:
        chip = QWidget()
        chip.setObjectName("metricChip")
        row = QHBoxLayout(chip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        icon_widget = MetricChipIcon(icon_kind)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        texts.addWidget(value_label)
        texts.addWidget(label_widget)
        row.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(texts)
        return chip, value_label, label_widget, icon_widget

    def _build_bottom_composer(self) -> QFrame:
        composer = QFrame()
        composer.setObjectName("composerPanel")
        layout = QVBoxLayout(composer)
        layout.setContentsMargins(14, 10, 14, 13)
        layout.setSpacing(5)

        self.request_edit = QTextEdit()
        self.request_edit.setPlaceholderText(EXAMPLE_REQUEST)
        self.request_edit.setMinimumHeight(self._request_min_height)
        self.request_edit.setMaximumHeight(self._request_max_height)
        self.request_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.request_edit.document().setDocumentMargin(0)
        self.request_edit.setObjectName("requestEdit")
        self.request_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.request_edit.textChanged.connect(self._sync_request_edit_height)
        self.request_edit.installEventFilter(self)
        layout.addWidget(self.request_edit)
        self._sync_request_edit_height()

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.attach_button = ComposerIconButton("attach", "Прикрепить файл")
        self.attach_button.clicked.connect(self.attach_files)
        toolbar.addWidget(self.attach_button)
        toolbar.addWidget(ComposerIconButton("database", "Источники данных"))

        self._init_model_controls()
        toolbar.addSpacing(4)
        toolbar.addWidget(self.model_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self.reason_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        toolbar.addWidget(self.refresh_models_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.context_indicator = ContextIndicator()
        toolbar.addWidget(self.context_indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        self.attach_clear_button = QPushButton("Очистить вложения")
        self.attach_clear_button.clicked.connect(self.clear_attachments)
        self.attach_label = QLabel("Файлы не прикреплены")
        self.attach_clear_button.setVisible(False)
        self.attach_label.setVisible(False)

        toolbar.addStretch(1)
        toolbar.addWidget(self._build_launch_split())
        layout.addLayout(toolbar)

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
            "border-top-right-radius:9px; border-bottom-right-radius:9px;"
            "}"
            "#launchSplitMenu::menu-indicator { width:0px; height:0px; border:none; }"
            "#launchSplitDivider { background:rgba(0,0,0,0.22); min-width:1px; max-width:1px; }"
            "#launchSplitMenu:hover { background:rgba(255,255,255,0.08); }"
            "#launchSplitStop {"
            "background:#5a2630; color:#ffc4ce; border:1px solid #8b3342;"
            "border-radius:7px; padding:8px 12px; font-size:12px; font-weight:700;"
            "}"
        )
        return composer

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # На каждом Resize пересчёт document height даёт layout thrashing при scale.
        if obj is self.request_edit and event.type() == QEvent.Type.Resize:
            self._schedule_request_edit_height_sync()
            return False
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_request_edit_height_sync()

    def _schedule_request_edit_height_sync(self) -> None:
        """Отложить пересчёт высоты поля запроса до конца серии resize/scale."""
        self._request_height_sync_pending = True
        self._resize_sync_timer.start()

    def _apply_deferred_resize_sync(self) -> None:
        if not self._request_height_sync_pending:
            return
        self._request_height_sync_pending = False
        self._sync_request_edit_height()

    def _sync_request_edit_height(self) -> None:
        """Подстраивать высоту поля запроса под число строк без обрезки текста."""
        edit = getattr(self, "request_edit", None)
        if edit is None:
            return
        viewport_width = max(40, edit.viewport().width())
        document = edit.document()
        if abs(document.textWidth() - viewport_width) < 1.0 and edit.height() > 0:
            # Ширина не изменилась — не трогаем layout во время непрерывного resize.
            doc_height = document.size().height()
        else:
            document.setTextWidth(viewport_width)
            doc_height = document.size().height()
        frame = edit.frameWidth() * 2
        margins = edit.contentsMargins()
        target = int(doc_height + frame + margins.top() + margins.bottom() + 2)
        target = max(self._request_min_height, min(self._request_max_height, target))
        if edit.height() != target:
            edit.setFixedHeight(target)
        if target >= self._request_max_height:
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.verticalScrollBar().setValue(0)

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
        self.refresh_models_button.setVisible(False)
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

        divider = QFrame()
        divider.setObjectName("launchSplitDivider")
        divider.setFixedWidth(1)
        divider.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Expanding,
        )
        row.addWidget(divider)

        menu_button = LaunchSplitMenuButton("")
        menu_button.setObjectName("launchSplitMenu")
        menu_button.setFixedSize(30, 28)
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
        """Правая панель плана и текущего шага без отдельной карточки-обёртки."""
        panel = QWidget()
        panel.setMinimumWidth(400)
        panel.setMaximumWidth(440)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 14, 16)
        layout.setSpacing(12)

        plan_header = QLabel("План")
        plan_header.setObjectName("planTitle")
        layout.addWidget(plan_header)

        self._plan_steps_list = PlanStepsList(self)
        for index, (stage_id, title, _subtitle) in enumerate(STAGE_ORDER[:8], start=1):
            row = PlanStepRow(index, stage_id, title, self)
            self._plan_step_cards[stage_id] = row
            self._plan_steps_list.add_step(row)
        layout.addWidget(self._plan_steps_list)

        layout.addStretch(1)

        self._current_step_section = QWidget()
        self._current_step_section.setObjectName("currentStepSection")
        current_layout = QVBoxLayout(self._current_step_section)
        current_layout.setContentsMargins(0, 0, 0, 0)
        current_layout.setSpacing(12)

        current_header = QLabel("Текущий шаг")
        current_header.setObjectName("sideTitle")
        current_layout.addWidget(current_header)

        self._current_step_card = CurrentStepCard()
        current_layout.addWidget(self._current_step_card)

        eta_row = QWidget()
        eta_row.setObjectName("etaRow")
        eta_row_layout = QHBoxLayout(eta_row)
        eta_row_layout.setContentsMargins(0, 4, 0, 0)
        eta_row_layout.setSpacing(6)
        self._eta_sidebar_icon = MetricChipIcon("eta")
        self.eta_label = QLabel("Ожидаемое завершение: —")
        self.eta_label.setObjectName("etaLabel")
        eta_row_layout.addWidget(self._eta_sidebar_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        eta_row_layout.addWidget(self.eta_label, 0, Qt.AlignmentFlag.AlignVCenter)
        current_layout.addWidget(eta_row)

        layout.addWidget(self._current_step_section)

        layout.addStretch(1)

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
            "#planTitle, #sideTitle { color:#f4f8ff; font-size:18px; font-weight:800; }"
            "#currentStepSection { background:transparent; }"
            "#etaLabel { color:#75869f; font-size:12px; font-weight:600; padding:0; }"
            "#etaRow { background:transparent; }"
            "#devToggle {"
            "text-align:left; background:transparent; color:#8fa1bd;"
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
        self.reason_combo.currentIndexChanged.connect(self._on_reason_combo_changed)

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
        self.reason_combo.blockSignals(True)
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
        if mode:
            reason_index = self.reason_combo.findData(mode)
            if reason_index >= 0:
                self.reason_combo.setCurrentIndex(reason_index)
        self.reason_combo.blockSignals(False)
        self._sync_reason_combo()
        self._fit_combo_to_contents(self.model_combo)
        self._fit_combo_to_contents(self.reason_combo)

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
            if base_model == "claude":
                # Старый прокси мог отдавать общий пункт "Claude"; в селекте
                # должны быть только конкретные Claude-модели (`claude-...`).
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
        self._persist_selected_model_choice()

    def _on_reason_combo_changed(self, _index: int) -> None:
        """Сохранить смену reasoning-режима."""
        self._fit_combo_to_contents(self.reason_combo)
        self._persist_selected_model_choice()

    def _sync_reason_combo(self) -> None:
        """Показать селект reason и подстроить доступные режимы под модель."""
        option = self._current_model_option()
        allowed = set(option.modes or ("internal", "reason")) if option else {"internal", "reason"}
        supports = bool(option and option.supports_reasoning)
        self.reason_combo.setEnabled(True)
        if supports:
            self.reason_combo.setToolTip("Режим reasoning для выбранной модели.")
        else:
            self.reason_combo.setToolTip(
                "Режим reasoning для выбранной модели (может быть недоступен у провайдера)."
            )
        mode = self.reason_combo.currentData()
        if mode not in allowed:
            for index in range(self.reason_combo.count()):
                if self.reason_combo.itemData(index) in allowed:
                    self.reason_combo.setCurrentIndex(index)
                    break
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
        self._persist_selected_model_choice(selected_model)
        if selected_model == config.llm_model_name:
            return
        self._append_log(f"⚙ Переключаю LLM-модель на {selected_model}…")
        new_config = config.model_copy(
            update={"llm_model_name": selected_model}
        )
        self._container = build_application_container(new_config)
        self._preview_agent = None
        self._update_workspace_button()

    def _persist_selected_model_choice(self, model_name: str | None = None) -> None:
        """Запомнить выбранный model id в локальных настройках."""
        selected_model = model_name or self._selected_model_id()
        try:
            save_llm_model_name(selected_model)
        except (OSError, ValueError) as exc:
            self._append_log(f"⚠ Не удалось сохранить выбранную LLM-модель: {exc}")

    # ---------------------------------------------------- background flow

    def _is_busy(self) -> bool:
        """Вернуть True, если уже выполняется фоновая операция."""
        return self._thread is not None

    def _append_log(self, message: str) -> None:
        """Добавить строку в живой лог хода выполнения."""
        if message.startswith("CTX_USAGE:"):
            try:
                usage = json.loads(message.removeprefix("CTX_USAGE:"))
            except json.JSONDecodeError:
                return
            if self.context_indicator is not None:
                self.context_indicator.set_usage(usage)
            return
        self.live_log.append(message)
        scrollbar = self.live_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self._update_stage_from_progress(message)
        self._refresh_run_header()

    def _start_run_tracking(self) -> None:
        """Start or resume the run header timer."""
        if self._run_started_at is None:
            self._run_started_at = time.monotonic()
        self._run_timer.start()
        self._refresh_run_header()

    def _stop_run_tracking(self) -> None:
        """Stop the timer and keep accumulated elapsed time."""
        if self._run_started_at is not None:
            self._run_elapsed_seconds = self._current_elapsed_seconds()
            self._run_started_at = None
        self._run_timer.stop()
        self._refresh_run_header()

    def _start_elapsed_timer(self, *, reset: bool) -> None:
        """Compatibility wrapper for the local elapsed-time flow."""
        if reset:
            self._run_elapsed_seconds = 0.0
            self._run_started_at = time.monotonic()
        elif self._run_started_at is None:
            self._run_started_at = time.monotonic()
        self._run_timer.start()
        self._refresh_run_header()

    def _pause_elapsed_timer(self) -> None:
        """Pause the timer and keep accumulated elapsed time."""
        self._stop_run_tracking()

    def _reset_elapsed_timer(self) -> None:
        """Reset elapsed time for a new run or clear action."""
        self._run_started_at = None
        self._run_elapsed_seconds = 0.0
        self._run_timer.stop()
        self._refresh_run_header()

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_eta_minutes(seconds: float) -> str:
        if seconds <= 0:
            return "—"
        minutes = max(1, int(round(seconds / 60)))
        return f"~{minutes} мин"

    def _current_elapsed_seconds(self) -> float:
        if self._run_started_at is not None:
            return self._run_elapsed_seconds + (time.monotonic() - self._run_started_at)
        return self._run_elapsed_seconds

    def _resolve_active_stage_id(self) -> str:
        for stage_id in TRACKED_STAGE_IDS:
            if self._stage_cards[stage_id]._status == "running":
                return stage_id
        for stage_id in TRACKED_STAGE_IDS:
            status = self._stage_cards[stage_id]._status
            if status in {
                "failed",
                "warning",
                "needs_human",
                "needs_credentials",
            }:
                return stage_id
        for stage_id in TRACKED_STAGE_IDS:
            if self._stage_cards[stage_id]._status == "pending":
                return stage_id
        return TRACKED_STAGE_IDS[-1]

    def _run_progress_percent(self) -> int:
        total = len(TRACKED_STAGE_IDS)
        passed = sum(
            1
            for stage_id in TRACKED_STAGE_IDS
            if self._stage_cards[stage_id]._status == "passed"
        )
        active_id = self._resolve_active_stage_id()
        active_status = self._stage_cards[active_id]._status
        progress = float(passed)
        if active_status == "running":
            progress += 0.5
        elif active_status == "passed" and active_id == TRACKED_STAGE_IDS[-1]:
            progress = float(total)
        return int(min(100, max(0, round(progress / total * 100))))

    def _header_step_title(self, stage_id: str) -> str:
        subtitle = self._stage_cards[stage_id]._subtitle.text().strip()
        default_subtitle = next(
            sub for sid, _, sub in STAGE_ORDER if sid == stage_id
        )
        if subtitle and subtitle not in {
            default_subtitle,
            "Стадия ещё не выполнялась.",
        }:
            return subtitle
        return WORKFLOW_STAGE_LABELS.get(stage_id, default_subtitle)

    def _run_header_status(self) -> str:
        if self._human_panel.isVisible():
            return "needs_human"
        if self._is_busy():
            return "running"
        for stage_id in TRACKED_STAGE_IDS:
            if self._stage_cards[stage_id]._status == "failed":
                return "failed"
        passed_count = sum(
            1
            for stage_id in TRACKED_STAGE_IDS
            if self._stage_cards[stage_id]._status == "passed"
        )
        if passed_count == len(TRACKED_STAGE_IDS):
            return "passed"
        return "pending"

    def _refresh_run_header(self) -> None:
        """Обновить метрики шапки по текущему состоянию этапов."""
        if not hasattr(self, "_elapsed_value_label"):
            return

        total_steps = len(TRACKED_STAGE_IDS)
        active_id = self._resolve_active_stage_id()
        active_index = TRACKED_STAGE_IDS.index(active_id) + 1
        progress = self._run_progress_percent()
        elapsed = self._current_elapsed_seconds()
        step_title = self._header_step_title(active_id)

        self._elapsed_value_label.setText(self._format_elapsed(elapsed))
        self._step_value_label.setText(f"Шаг {active_index} из {total_steps}")
        self._step_detail_label.setText(step_title)
        self.run_progress.setValue(progress)
        self._progress_percent_label.setText(f"{progress}%")

        if self._is_busy() and progress > 0:
            remaining = elapsed * (100 - progress) / progress
            eta_text = self._format_eta_minutes(remaining)
        elif progress >= 100:
            eta_text = "0 мин"
        else:
            eta_text = "—"
        self._eta_header_value_label.setText(eta_text)
        if hasattr(self, "eta_label"):
            self.eta_label.setText(f"Ожидаемое завершение: {eta_text}")

        is_active = self._is_busy()
        for icon in (
            getattr(self, "_elapsed_icon", None),
            getattr(self, "_step_icon", None),
            getattr(self, "_eta_icon", None),
            getattr(self, "_eta_sidebar_icon", None),
        ):
            if icon is not None:
                icon.set_active(is_active)

        status_key = self._run_header_status()
        badge_text, badge_style = self._status_badge_stylesheet(status_key)
        self.run_status_badge.setText(badge_text)
        self.run_status_badge.setStyleSheet(badge_style)

    def _update_stage_from_progress(self, message: str) -> None:
        """Сопоставить live-сообщения с активным этапом workflow."""
        lower = message.lower()
        if "остановк" in lower:
            return
        if "строю план" in lower:
            self._set_running(STAGE_PLAN)
            self._stage_details[STAGE_PLAN] = message.strip()
            return
        if "план построен" in lower:
            self._set_stage(STAGE_PLAN, "passed", "План LLM построен", message.strip())
            self._set_running(STAGE_TRIAL)
            self._stage_details[STAGE_TRIAL] = message.strip()
            return
        if self._stage_cards[STAGE_TRIAL]._status == "running":
            self._stage_details[STAGE_TRIAL] = message.strip()
            if self._selected_stage == STAGE_TRIAL:
                self._refresh_current_step_card()

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
        self._start_run_tracking()
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
        self._stop_run_tracking()

    def request_stop(self) -> None:
        """Запросить остановку: прерывает ожидание ответа LLM и шаги цикла."""
        if not self._is_busy():
            return
        self._cancel_event.set()
        self.stop_button.setEnabled(False)
        if self._launch_stop_action is not None:
            self._launch_stop_action.setEnabled(False)
        self._append_log(
            "⏹ Запрошена остановка агента. Прерываю текущий запрос к модели…"
        )

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
        self._start_elapsed_timer(reset=True)
        self.live_log.clear()
        self._ensure_selected_model_container()
        self._cancel_event.clear()
        self._last_request = user_request
        self._set_stage(STAGE_REQUEST, "passed", _short(user_request), user_request)
        self._set_running(STAGE_PLAN)
        self.select_stage(STAGE_PLAN)

        service = self._container.agent_service
        cancel_event = self._cancel_event

        def job(progress: Callable[[str], None]) -> object:
            progress("🧩 Строю план агента через LLM…")
            spec = service.build_preview(
                user_request,
                cancel_callback=cancel_event.is_set,
            )
            progress("✅ План построен.")
            return spec

        self._run_in_background(job, self._on_preview_completed, self._on_preview_failed)

    def _on_preview_completed(self, spec: object) -> None:
        """Отобразить построенный preview AgentSpec."""
        assert isinstance(spec, AgentSpec)
        self._preview_agent = spec
        self._update_workspace_button()
        self._render_preview(spec)
        self._render_plan_stages(spec)
        self.select_stage(STAGE_PLAN)
        self._pause_elapsed_timer()

    def _on_preview_failed(self, message: str) -> None:
        """Показать ошибку построения плана."""
        self._set_stage(STAGE_PLAN, "failed", "Не удалось построить план", message)
        self._append_log(f"⚠ Ошибка предпросмотра: {message}")
        self._pause_elapsed_timer()
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
            self._start_elapsed_timer(reset=True)
            self._set_stage(STAGE_REQUEST, "passed", _short(request), request)
        elif self._run_started_at is None and self._run_elapsed_seconds == 0.0:
            self._start_elapsed_timer(reset=True)
        else:
            self._start_elapsed_timer(reset=False)
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
        self._update_workspace_button()
        self._render_preview(spec)
        self._render_plan_stages(spec)
        self._apply_validation(validation)
        self.select_stage(STAGE_RESULT)
        self._pause_elapsed_timer()
        show_info(self, "Проверка агента", validation.summary)

    def _on_validate_failed(self, message: str) -> None:
        """Показать ошибку пробного запуска."""
        self._set_stage(STAGE_TRIAL, "failed", "Ошибка пробного запуска", message)
        self._append_log(f"⚠ Ошибка проверки агента: {message}")
        self._pause_elapsed_timer()
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
        self._start_elapsed_timer(reset=True)
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
        self._update_workspace_button()
        self._render_preview(agent_spec)
        self._render_plan_stages(agent_spec)
        self._apply_validation(validation)
        self.select_stage(STAGE_RESULT)
        if self._is_run_cancelled(validation, state):
            self._hide_human_panel()
            self._set_stage(
                STAGE_TRIAL,
                "warning",
                "Остановлено пользователем",
                validation.summary,
            )
            return
        if state is None:
            self._hide_human_panel()
            self._pause_elapsed_timer()
            show_info(self, "Агент не запущен", validation.summary)
            return
        self._update_context_indicator(state)
        if self._is_awaiting_human(state):
            self._prompt_human(agent_spec, state)
            return
        self._hide_human_panel()
        self._show_produced_files(agent_spec, state)
        self._pause_elapsed_timer()
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

    def _update_context_indicator(self, state: object | None) -> None:
        """Обновить круговой индикатор из context_snapshot runtime state."""
        if self.context_indicator is None:
            return
        variables = getattr(state, "variables", {}) or {}
        snapshot = variables.get("context_snapshot") if isinstance(variables, dict) else None
        usage = snapshot.get("usage") if isinstance(snapshot, dict) else None
        self.context_indicator.set_usage(usage)

    @staticmethod
    def _is_awaiting_human(state: object) -> bool:
        """Проверить, приостановлен ли запуск и ждёт участия человека."""
        return getattr(state, "status", None) in {
            AgentRunStatus.PAUSED_FOR_HUMAN,
            AgentRunStatus.PAUSED_FOR_CREDENTIALS,
        }

    def _is_run_cancelled(self, validation, state: object | None) -> bool:
        """Проверить, что запуск завершился по кнопке «Остановить»."""
        if self._cancel_event.is_set():
            return True
        if getattr(state, "status", None) == AgentRunStatus.CANCELLED:
            return True
        summary = (getattr(validation, "summary", None) or "").strip().lower()
        return summary in {
            "выполнение остановлено пользователем.",
            "пробный запуск остановлен пользователем.",
            "построение плана остановлено пользователем.",
        } or "остановлено пользователем" in summary

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
        self._pause_elapsed_timer()
        self._append_log("⏸ Агент ожидает вашего ответа/действия. Ответьте и нажмите «Продолжить».")
        self._refresh_run_header()

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
        self._refresh_run_header()

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
        self._start_elapsed_timer(reset=False)
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
        self._pause_elapsed_timer()
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
            self._update_workspace_button()
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

    def open_agent_workspace(self) -> None:
        """Открыть папку документов текущего preview/созданного агента."""
        if self._preview_agent is None:
            show_info(
                self,
                "Папка агента пока недоступна",
                "Сначала создайте preview или сохраните агента.",
            )
            return
        service = self._container.agent_service
        if not hasattr(service, "agent_workspace_dir"):
            show_error(self, "Папка недоступна", "Сервис не поддерживает workspace агента.")
            return
        folder = service.agent_workspace_dir(self._preview_agent.agent_id)
        if not folder:
            show_error(self, "Папка недоступна", "Не удалось определить папку агента.")
            return
        open_local_path(folder)

    def _update_workspace_button(self) -> None:
        """Обновить доступность кнопки папки агента."""
        if self.open_workspace_button is not None:
            self.open_workspace_button.setEnabled(self._preview_agent is not None)

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
        self._update_workspace_button()
        self.clear_attachments()
        self._hide_human_panel()
        self.request_edit.clear()
        self.live_log.clear()
        self.files_label.setVisible(False)
        self._update_context_indicator(None)
        self._reset_elapsed_timer()
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
        self._run_started_at = None
        self._run_elapsed_seconds = 0.0
        self._run_timer.stop()
        self._refresh_run_header()

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
        self._refresh_run_header()

    def _set_running(self, stage_id: str) -> None:
        """Пометить стадию как выполняющуюся."""
        self._stage_cards[stage_id].set_status("running")
        if stage_id in self._plan_step_cards:
            self._plan_step_cards[stage_id].set_status("running")
        if self._selected_stage == stage_id:
            self._refresh_current_step_card()
        self._refresh_run_header()

    def _stage_plan_index(self, stage_id: str) -> int:
        for index, (sid, _, _) in enumerate(STAGE_ORDER[:8], start=1):
            if sid == stage_id:
                return index
        return 1

    def _current_step_title(self, stage_id: str) -> str:
        card = self._stage_cards[stage_id]
        subtitle = card._subtitle.text().strip()
        if subtitle:
            return subtitle
        return next(title for sid, title, _ in STAGE_ORDER if sid == stage_id)

    def _current_step_detail_text(self, stage_id: str, status: str) -> str:
        if status == "running":
            detail = (self._stage_details.get(stage_id) or "").strip()
            for line in detail.splitlines():
                cleaned = line.strip()
                if not cleaned:
                    continue
                lowered = cleaned.lower()
                if lowered.startswith("выполняю:"):
                    return cleaned
                if "." in cleaned and len(cleaned) <= 80 and " " not in cleaned:
                    return f"Выполняю: {cleaned}"
                if " — " in cleaned:
                    tool_name = cleaned.split(" — ", 1)[0].strip("• ").strip()
                    if tool_name:
                        return f"Выполняю: {tool_name}"
            subtitle = self._current_step_title(stage_id)
            if subtitle and subtitle != "Стадия ещё не выполнялась.":
                return f"Выполняю: {_short(subtitle, 55)}"
            return "Выполняю шаг"
        if status == "passed":
            return "Шаг выполнен"
        if status == "pending":
            return "Ожидает начала"
        label, _, _, _ = STATUS_STYLE.get(status, STATUS_STYLE["pending"])
        return f"Статус: {label}"

    def _refresh_current_step_card(self) -> None:
        if self._selected_stage is None:
            return
        stage_id = self._selected_stage
        card = self._stage_cards[stage_id]
        self._current_step_card.set_content(
            self._stage_plan_index(stage_id),
            self._current_step_title(stage_id),
            self._current_step_detail_text(stage_id, card._status),
            card._status,
        )

    def select_stage(self, stage_id: str) -> None:
        """Показать детали выбранной стадии в правой панели."""
        self._selected_stage = stage_id
        for other_id, card in self._stage_cards.items():
            card.set_selected(other_id == stage_id)
        for other_id, card in self._plan_step_cards.items():
            card.set_active(other_id == stage_id)
        self._refresh_current_step_card()
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
