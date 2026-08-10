"""Круговой индикатор использования контекста агента."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from agent_desktop_constructor.app.context.models import ContextSection, ContextUsage


SECTION_LABELS: dict[str, str] = {
    "creation": "Создание",
    "run": "Выполнение",
    "events": "События",
    "tool_results": "Инструменты",
    "pause": "Пауза",
    "agent_call": "Вызов агента",
    "user_history": "История",
    "persistent": "Постоянный",
    "temporary": "Временный",
}

SECTION_COLORS: dict[str, str] = {
    "creation": "#60a5fa",
    "run": "#34d399",
    "events": "#fbbf24",
    "tool_results": "#a78bfa",
    "pause": "#fb7185",
    "agent_call": "#38bdf8",
    "user_history": "#f472b6",
    "persistent": "#22c55e",
    "temporary": "#94a3b8",
}

POPOVER_MARGIN = 8
SCREEN_PADDING = 6


def _bounded_percent(value: Any) -> float:
    """Вернуть процент в пределах 0..100."""
    return max(0.0, min(float(value or 0.0), 100.0))


def _usage_color(percent: float) -> str:
    """Цвет кольца по уровню заполнения контекста."""
    if percent <= 0:
        return "#64748b"
    if percent < 35:
        return "#38bdf8"
    if percent < 70:
        return "#22c55e"
    if percent < 88:
        return "#f59e0b"
    return "#ef4444"


def _popover_position(
    indicator_top_left: QPoint,
    indicator_size: QSize,
    popover_size: QSize,
    available_rect: QRect,
    margin: int = POPOVER_MARGIN,
) -> QPoint:
    """Рассчитать позицию popover над индикатором с fallback вниз."""
    x = indicator_top_left.x() + (indicator_size.width() - popover_size.width()) // 2
    min_x = available_rect.left() + SCREEN_PADDING
    max_x = available_rect.right() - popover_size.width() - SCREEN_PADDING
    if max_x < min_x:
        max_x = min_x
    x = max(min_x, min(x, max_x))

    top_limit = available_rect.top() + SCREEN_PADDING
    above_y = indicator_top_left.y() - popover_size.height() - margin
    if above_y >= top_limit:
        return QPoint(x, above_y)

    below_y = indicator_top_left.y() + indicator_size.height() + margin
    bottom_limit = available_rect.bottom() - popover_size.height() - SCREEN_PADDING
    if bottom_limit < top_limit:
        bottom_limit = top_limit
    return QPoint(x, max(top_limit, min(below_y, bottom_limit)))


class ContextIndicator(QWidget):
    """Кольцевой индикатор общего заполнения и popover по секциям."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._usage: dict[str, Any] = {
            "total_chars": 0,
            "total_limit": 1,
            "total_percent": 0.0,
            "section_chars": {},
            "section_percent": {},
        }
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._tooltip_text())

    def set_usage(self, usage: ContextUsage | dict[str, Any] | None) -> None:
        """Обновить usage-метрики индикатора."""
        if usage is None:
            self._usage = {
                "total_chars": 0,
                "total_limit": 1,
                "total_percent": 0.0,
                "section_chars": {},
                "section_percent": {},
            }
        elif isinstance(usage, ContextUsage):
            self._usage = usage.model_dump(mode="json")
        else:
            self._usage = usage
        self.setToolTip(self._tooltip_text())
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Открыть popover со статистикой по секциям."""
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        menu = self._build_menu()
        menu_size = menu.sizeHint()
        screen = self.screen() or QGuiApplication.screenAt(self.mapToGlobal(QPoint(0, 0)))
        available_rect = (
            screen.availableGeometry()
            if screen is not None
            else QRect(self.mapToGlobal(QPoint(-500, -500)), QSize(1000, 1000))
        )
        menu.exec(
            _popover_position(
                self.mapToGlobal(QPoint(0, 0)),
                self.size(),
                menu_size,
                available_rect,
            )
        )

    def _build_menu(self) -> QMenu:
        """Собрать стилизованный popover со статистикой по секциям."""
        menu = QMenu(self)
        menu.setObjectName("contextIndicatorPopover")
        menu.setStyleSheet(
            """
            QMenu#contextIndicatorPopover {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 8px;
                color: #e2e8f0;
            }
            QMenu#contextIndicatorPopover::item {
                border-radius: 6px;
                padding: 6px 12px;
                margin: 1px 0;
            }
            QMenu#contextIndicatorPopover::item:selected {
                background-color: #1e293b;
            }
            QMenu#contextIndicatorPopover::separator {
                height: 1px;
                background: #334155;
                margin: 7px 4px;
            }
            """
        )
        total_percent = float(self._usage.get("total_percent") or 0.0)
        total_chars = int(self._usage.get("total_chars") or 0)
        total_limit = int(self._usage.get("total_limit") or 0)
        header = menu.addAction("Контекст агента")
        header.setEnabled(False)
        menu.addAction(f"Всего: {total_percent:.1f}% - {total_chars}/{total_limit} симв.")
        prompt_chars = self._usage.get("prompt_payload_chars")
        prompt_limit = self._usage.get("prompt_payload_limit")
        if isinstance(prompt_chars, int) and prompt_chars > 0:
            prompt_percent = float(self._usage.get("prompt_payload_percent") or 0.0)
            menu.addAction(
                f"LLM prompt: {prompt_percent:.1f}% - "
                f"{prompt_chars}/{int(prompt_limit or 0)} симв."
            )
        menu.addSeparator()
        section_chars = self._usage.get("section_chars") or {}
        section_percent = self._usage.get("section_percent") or {}
        for section in ContextSection:
            key = section.value
            chars = int(section_chars.get(key) or 0)
            percent = float(section_percent.get(key) or 0.0)
            menu.addAction(f"{SECTION_LABELS[key]}: {percent:.1f}% ({chars} симв.)")
        return menu

    def paintEvent(self, event) -> None:  # noqa: N802
        """Нарисовать кольцо заполнения."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        total_percent = _bounded_percent(self._usage.get("total_percent"))

        painter.setPen(
            QPen(
                QColor("#1e293b"),
                4,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawEllipse(rect)

        if total_percent > 0:
            span = int(-360 * 16 * (total_percent / 100))
            painter.setPen(
                QPen(
                    QColor(_usage_color(total_percent)),
                    4,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawArc(rect, 90 * 16, span)

        font = painter.font()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#e2e8f0" if total_percent > 0 else "#94a3b8"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{int(total_percent)}%")

    def _tooltip_text(self) -> str:
        total_percent = float(self._usage.get("total_percent") or 0.0)
        total_chars = int(self._usage.get("total_chars") or 0)
        total_limit = int(self._usage.get("total_limit") or 0)
        prompt_chars = self._usage.get("prompt_payload_chars")
        prompt_extra = ""
        if isinstance(prompt_chars, int) and prompt_chars > 0:
            prompt_limit = int(self._usage.get("prompt_payload_limit") or 0)
            prompt_percent = float(self._usage.get("prompt_payload_percent") or 0.0)
            prompt_extra = (
                f" LLM prompt: {prompt_percent:.1f}% "
                f"({prompt_chars}/{prompt_limit})."
            )
        return (
            "Использование контекста агента: "
            f"{total_percent:.1f}% ({total_chars}/{total_limit} симв.)."
            f"{prompt_extra} "
            "Нажмите, чтобы увидеть разбивку по секциям."
        )
