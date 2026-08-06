"""Боковая навигация по референсу: логотип + пункты меню."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.ui.resources_paths import (
    brand_logo_path,
    brand_logo_svg_fallback_path,
    nav_icon_path,
    nav_icon_svg_path,
)
from agent_desktop_constructor.app.ui.ui_resource_loader import load_scaled_pixmap

NAV_WIDTH = 270
SETTINGS_PAGE_INDEX = 5

_NAV_ICON_PX = 28
_NAV_ICON_BOX = 34
# У «Аналитики» в PNG больше отступов — рендерим крупнее для визуального паритета.
_NAV_ICON_RENDER_OVERRIDES: dict[str, int] = {
    "analytics": 34,
}
_NAV_ROW_HEIGHT = 52
_HEADER_LOGO_W = 220
_HEADER_LOGO_H = 48

_BG = "#0B0B14"
_ACTIVE_BG = "#1a1830"
_ACCENT = "#5856D6"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"


@dataclass(frozen=True)
class NavItemSpec:
    """Описание пункта навигации."""

    title: str
    icon_name: str
    is_settings: bool = False


NAV_ITEMS: tuple[NavItemSpec, ...] = (
    NavItemSpec("Главная", "home"),
    NavItemSpec("Доступные агенты", "agents"),
    NavItemSpec("Конструктор", "constructor"),
    NavItemSpec("Мои задания", "tasks"),
    NavItemSpec("Аналитика", "analytics"),
    NavItemSpec("Настройки", "settings", is_settings=True),
)


class NavPixmapIcon(QLabel):
    """Иконка пункта меню из PNG или SVG fallback."""

    def __init__(self, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._active = False
        self.setFixedSize(_NAV_ICON_BOX, _NAV_ICON_BOX)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reload()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._reload()

    def _render_size(self) -> int:
        return _NAV_ICON_RENDER_OVERRIDES.get(self._icon_name, _NAV_ICON_PX)

    def _reload(self) -> None:
        render_px = self._render_size()
        png_path = nav_icon_path(self._icon_name)
        pix = QPixmap()
        if png_path.exists():
            pix = load_scaled_pixmap(png_path, render_px, render_px)

        if pix.isNull():
            svg_path = nav_icon_svg_path(self._icon_name, active=self._active)
            if svg_path is not None and svg_path.exists():
                pix = load_scaled_pixmap(svg_path, render_px, render_px)

        if pix.isNull():
            self.setText("•")
            self.setStyleSheet(
                f"color:{_TEXT if self._active else _MUTED}; font-size:18px;"
                "background:transparent;"
            )
            return

        self.setText("")
        self.setPixmap(pix)
        self.setStyleSheet("background:transparent;")


class NavIconButton(QFrame):
    """Кнопка навигации с индикатором активной вкладки."""

    clicked = Signal(int)

    def __init__(
        self,
        index: int,
        spec: NavItemSpec,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.index = index
        self._spec = spec
        self._active = False

        self._indicator = QFrame(self)
        self._indicator.setFixedWidth(3)
        self._indicator.setFixedHeight(34)

        self._button = QToolButton()
        self._button.setAutoRaise(True)
        self._button.setFixedSize(0, 0)
        self._button.setToolTip(spec.title)
        self._button.clicked.connect(lambda: self.clicked.emit(self.index))

        self._icon = NavPixmapIcon(spec.icon_name, self)
        self._label = QLabel(spec.title)
        self._label.setObjectName("navLabel")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 10, 0)
        row.setSpacing(12)
        row.addWidget(self._indicator)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._button)

        self.setFixedHeight(_NAV_ROW_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_state()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_state()

    def _apply_state(self) -> None:
        self._icon.set_active(self._active)
        indicator_color = _ACCENT if self._active else "transparent"
        bg_color = _ACTIVE_BG if self._active else "transparent"
        label_color = _TEXT if self._active else _MUTED
        self._indicator.setStyleSheet(
            f"background: {indicator_color}; border-radius: 2px;"
        )
        self.setStyleSheet(
            "NavIconButton {"
            f"background:{bg_color}; border-radius:10px;"
            "}"
            "NavIconButton:hover { background:#141428; }"
            f"#navLabel {{ color:{label_color}; font-size:13px; font-weight:600; }}"
        )


class TeamsNavSidebar(QWidget):
    """Левая панель с логотипом и пунктами навигации."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[NavIconButton] = []
        self._current_index = -1

        self.setFixedWidth(NAV_WIDTH)
        self.setObjectName("teamsNavSidebar")

        header = QHBoxLayout()
        header.setContentsMargins(12, 12, 12, 16)
        header.setSpacing(10)

        logo = QLabel()
        logo.setObjectName("navLogo")
        logo_path = brand_logo_path()
        pix = QPixmap()
        if logo_path.exists():
            pix = load_scaled_pixmap(logo_path, _HEADER_LOGO_W, _HEADER_LOGO_H)
        if pix.isNull():
            fallback = brand_logo_svg_fallback_path()
            if fallback.exists():
                pix = load_scaled_pixmap(fallback, 40, 40)
        if not pix.isNull():
            logo.setPixmap(pix)
        else:
            logo.setText("Конструктор ИИ-агентов")
            logo.setStyleSheet(f"color:{_TEXT}; font-size:12px; font-weight:700;")
        header.addWidget(logo, 1)

        top = QVBoxLayout()
        top.setContentsMargins(10, 0, 10, 8)
        top.setSpacing(6)

        bottom = QVBoxLayout()
        bottom.setContentsMargins(10, 8, 10, 12)
        bottom.setSpacing(4)

        for index, spec in enumerate(NAV_ITEMS):
            button = NavIconButton(index, spec, self)
            button.clicked.connect(self.setCurrentIndex)
            self._buttons.append(button)
            if spec.is_settings:
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
            f"#teamsNavSidebar {{ background: {_BG}; border-right: 1px solid #1c1c2e; }}"
            "QToolButton { background: transparent; border: none; }"
        )

    def count(self) -> int:
        return len(self._buttons)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        if index < 0 or index >= len(self._buttons):
            return
        if index == self._current_index:
            return
        self._current_index = index
        for button_index, button in enumerate(self._buttons):
            button.set_active(button_index == index)
        self.currentIndexChanged.emit(index)

    def setCurrentRow(self, index: int) -> None:
        self.setCurrentIndex(index)

    def currentRow(self) -> int:
        return self.currentIndex()
