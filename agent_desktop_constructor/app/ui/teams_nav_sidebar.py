"""Боковая навигация в стиле Microsoft Teams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

ICONS_DIR = Path(__file__).resolve().parent / "resources" / "icons"
NAV_WIDTH = 72
ICON_SIZE = 28
SETTINGS_PAGE_INDEX = 3


@dataclass(frozen=True)
class NavItemSpec:
    """Описание пункта навигации."""

    title: str
    default_icon: str
    active_icon: str


NAV_ITEMS: tuple[NavItemSpec, ...] = (
    NavItemSpec("Агенты", "agents_default.svg", "agents_active.svg"),
    NavItemSpec("Создать агента", "create_default.svg", "create_active.svg"),
    NavItemSpec("Журнал", "journal_default.svg", "journal_active.svg"),
    NavItemSpec("Настройки", "settings_default.svg", "settings_active.svg"),
)


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

        self._indicator = QFrame()
        self._indicator.setFixedWidth(3)
        self._indicator.setFixedHeight(28)
        self._indicator.setStyleSheet(
            "background: transparent; border-radius: 2px;"
        )

        self._button = QToolButton()
        self._button.setAutoRaise(True)
        self._button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._button.setFixedSize(48, 48)
        self._button.setToolTip(spec.title)
        self._button.clicked.connect(lambda: self.clicked.emit(self.index))

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._indicator)
        row.addStretch(1)
        row.addWidget(self._button, 0, Qt.AlignmentFlag.AlignHCenter)
        row.addStretch(1)

        self.setFixedHeight(52)
        self._apply_state()

    def set_active(self, active: bool) -> None:
        """Переключить активное состояние."""
        self._active = active
        self._apply_state()

    def _icon_path(self, filename: str) -> str:
        return str(ICONS_DIR / filename)

    def _apply_state(self) -> None:
        icon_file = (
            self._spec.active_icon if self._active else self._spec.default_icon
        )
        self._button.setIcon(QIcon(self._icon_path(icon_file)))
        indicator_color = "#6264a7" if self._active else "transparent"
        bg_color = "#1f1f23" if self._active else "transparent"
        self._indicator.setStyleSheet(
            f"background: {indicator_color}; border-radius: 2px;"
        )
        self.setStyleSheet(f"NavIconButton {{ background: {bg_color}; }}")


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

        top = QVBoxLayout()
        top.setContentsMargins(0, 12, 0, 8)
        top.setSpacing(4)

        bottom = QVBoxLayout()
        bottom.setContentsMargins(0, 8, 0, 12)
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
        layout.addLayout(top)
        layout.addStretch(1)
        layout.addLayout(bottom)

        self.setStyleSheet(
            "#teamsNavSidebar { background: #0b0b0d; border-right: 1px solid #1f1f23; }"
            "QToolButton { background: transparent; border: none; }"
            "QToolButton:hover { background: #1a1a1e; border-radius: 8px; }"
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
