"""Боковая навигация в стиле референса Cursor-like UI."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

NAV_WIDTH = 188
SETTINGS_PAGE_INDEX = 4


@dataclass(frozen=True)
class NavItemSpec:
    """Описание пункта навигации."""

    title: str
    icon_kind: str


NAV_ITEMS: tuple[NavItemSpec, ...] = (
    NavItemSpec("Агенты", "user"),
    NavItemSpec("Создать агента", "plus"),
    NavItemSpec("Запуски", "play"),
    NavItemSpec("События", "bell"),
    NavItemSpec("Настройки", "gear"),
)


class NavVectorIcon(QWidget):
    """Тонкая линейная иконка как в левой панели референса."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._active = False
        self.setFixedSize(22, 22)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#e8f1ff" if self._active else "#8a98ad")
        pen = QPen(color, 1.45)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.kind == "user":
            painter.drawEllipse(QRectF(8, 3.2, 6, 6))
            path = QPainterPath(QPointF(4.5, 18.5))
            path.cubicTo(QPointF(5.5, 13.2), QPointF(16.5, 13.2), QPointF(17.5, 18.5))
            painter.drawPath(path)
        elif self.kind == "plus":
            painter.setBrush(QColor("#2f7cff" if self._active else "#132945"))
            painter.drawEllipse(QRectF(2.2, 2.2, 17.6, 17.6))
            painter.setPen(QPen(QColor("#ffffff" if self._active else "#8bb7ff"), 1.7))
            painter.drawLine(QPointF(11, 6.8), QPointF(11, 15.2))
            painter.drawLine(QPointF(6.8, 11), QPointF(15.2, 11))
        elif self.kind == "play":
            painter.drawEllipse(QRectF(2.5, 2.5, 17, 17))
            path = QPainterPath(QPointF(9, 7.2))
            path.lineTo(QPointF(15.2, 11))
            path.lineTo(QPointF(9, 14.8))
            path.closeSubpath()
            painter.drawPath(path)
        elif self.kind == "bell":
            path = QPainterPath(QPointF(6, 15.5))
            path.cubicTo(QPointF(7.1, 13.7), QPointF(7.2, 11.2), QPointF(7.2, 9.2))
            path.cubicTo(QPointF(7.2, 5.9), QPointF(9.1, 4), QPointF(11, 4))
            path.cubicTo(QPointF(12.9, 4), QPointF(14.8, 5.9), QPointF(14.8, 9.2))
            path.cubicTo(QPointF(14.8, 11.2), QPointF(14.9, 13.7), QPointF(16, 15.5))
            path.lineTo(QPointF(6, 15.5))
            painter.drawPath(path)
            painter.drawLine(QPointF(9.3, 18), QPointF(12.7, 18))
        else:
            painter.drawEllipse(QRectF(6.2, 6.2, 9.6, 9.6))
            for angle in range(0, 360, 45):
                painter.save()
                painter.translate(QPointF(11, 11))
                painter.rotate(angle)
                painter.drawLine(QPointF(0, -9.2), QPointF(0, -7.2))
                painter.restore()


class NavIconButton(QFrame):
    """Кнопка навигации с индикатором активной вкладки."""

    clicked = Signal(int)

    def __init__(
        self,
        index: int,
        spec: NavItemSpec,
        parent: QWidget | None = None,
    ) -> None:
        """Создать кнопку навигации."""
        super().__init__(parent)
        self.index = index
        self._spec = spec
        self._active = False

        self._indicator = QFrame(self)
        self._indicator.setFixedWidth(3)
        self._indicator.setFixedHeight(28)
        self._indicator.setStyleSheet(
            "background: transparent; border-radius: 2px;"
        )

        self._button = QToolButton()
        self._button.setAutoRaise(True)
        self._button.setFixedSize(0, 0)
        self._button.setToolTip(spec.title)
        self._button.clicked.connect(lambda: self.clicked.emit(self.index))

        self._icon = NavVectorIcon(spec.icon_kind, self)
        self._label = QLabel(spec.title)
        self._label.setObjectName("navLabel")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 10, 0)
        row.setSpacing(10)
        row.addWidget(self._indicator)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._button)

        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_state()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        """Переключить активное состояние."""
        self._active = active
        self._apply_state()

    def _apply_state(self) -> None:
        self._icon.set_active(self._active)
        indicator_color = "#2f7cff" if self._active else "transparent"
        bg_color = "#0f2340" if self._active else "transparent"
        label_color = "#eaf2ff" if self._active else "#9aa8ba"
        self._indicator.setStyleSheet(
            f"background: {indicator_color}; border-radius: 2px;"
        )
        self.setStyleSheet(
            "NavIconButton {"
            f"background:{bg_color}; border-radius:10px;"
            "}"
            "NavIconButton:hover { background:#0d1b30; }"
            f"#navLabel {{ color:{label_color}; font-size:13px; font-weight:600; }}"
        )


class TeamsNavSidebar(QWidget):
    """Узкая левая панель с иконками, как в Microsoft Teams."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Создать панель навигации."""
        super().__init__(parent)
        self._buttons: list[NavIconButton] = []
        self._current_index = -1

        self.setFixedWidth(NAV_WIDTH)
        self.setObjectName("teamsNavSidebar")

        header = QHBoxLayout()
        header.setContentsMargins(10, 8, 10, 12)
        header.setSpacing(8)

        logo = QLabel("✦")
        logo.setFixedSize(18, 18)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "background:#152640; color:#9dc2ff; border:1px solid #263a58;"
            "border-radius:4px; font-size:11px; font-weight:800;"
        )
        title = QLabel("Конструктор ИИ-агентов")
        title.setStyleSheet("color:#d7e2f5; font-size:12px; font-weight:700;")
        header.addWidget(logo)
        header.addWidget(title, 1)

        top = QVBoxLayout()
        top.setContentsMargins(10, 0, 10, 8)
        top.setSpacing(8)

        bottom = QVBoxLayout()
        bottom.setContentsMargins(10, 8, 10, 12)
        bottom.setSpacing(4)

        for index, spec in enumerate(NAV_ITEMS):
            button = NavIconButton(index, spec, self)
            button.clicked.connect(self.setCurrentIndex)
            self._buttons.append(button)
            if index == SETTINGS_PAGE_INDEX:
                bottom.addWidget(button)
            else:
                top.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addLayout(top)
        layout.addStretch(1)
        layout.addLayout(bottom)

        self.setStyleSheet(
            "#teamsNavSidebar { background: #07111f; border-right: 1px solid #11243d; }"
            "QToolButton { background: transparent; border: none; }"
        )

    def count(self) -> int:
        """Количество пунктов навигации."""
        return len(self._buttons)

    def currentIndex(self) -> int:
        """Индекс выбранной вкладки."""
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        """Выбрать вкладку по индексу."""
        if index < 0 or index >= len(self._buttons):
            return
        if index == self._current_index:
            return
        self._current_index = index
        for button_index, button in enumerate(self._buttons):
            button.set_active(button_index == index)
        self.currentIndexChanged.emit(index)

    def setCurrentRow(self, index: int) -> None:
        """Совместимость с прежним API QListWidget."""
        self.setCurrentIndex(index)

    def currentRow(self) -> int:
        """Совместимость с прежним API QListWidget."""
        return self.currentIndex()
