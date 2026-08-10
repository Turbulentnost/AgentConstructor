"""Верхняя панель приложения: заголовок страницы, создать, профиль."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ACCENT = "#5856D6"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"
_MENU_BG = "#161625"
_MENU_BORDER = "#2a2a3d"
_MENU_HOVER = "#22223a"


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    return "".join(p[0] for p in parts[:2]).upper()


class _ProfileMenuPopup(QFrame):
    """Локальный popup под ФИО (не QMenu — корректнее на мультимониторе)."""

    settings_clicked = Signal()
    logout_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hdrProfileMenu")
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setStyleSheet(
            f"#hdrProfileMenu {{ background: {_MENU_BG}; color: {_TEXT};"
            f"border: 1px solid {_MENU_BORDER}; border-radius: 10px; }}"
            f"#hdrMenuBtn {{ background: transparent; color: {_TEXT}; border: none;"
            "border-radius: 8px; padding: 10px 16px; font-size: 13px; font-weight: 600;"
            "text-align: left; }}"
            f"#hdrMenuBtn:hover {{ background: {_MENU_HOVER}; }}"
            f"#hdrMenuSep {{ background: {_MENU_BORDER}; max-height: 1px; min-height: 1px; }}"
        )

        settings_btn = QPushButton("Настройки")
        settings_btn.setObjectName("hdrMenuBtn")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self._on_settings)

        logout_btn = QPushButton("Выйти")
        logout_btn.setObjectName("hdrMenuBtn")
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.clicked.connect(self._on_logout)

        sep = QFrame()
        sep.setObjectName("hdrMenuSep")
        sep.setFrameShape(QFrame.Shape.HLine)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        layout.addWidget(settings_btn)
        layout.addWidget(sep)
        layout.addWidget(logout_btn)
        self.setFixedWidth(200)

    def _on_settings(self) -> None:
        self.hide()
        self.settings_clicked.emit()

    def _on_logout(self) -> None:
        self.hide()
        self.logout_clicked.emit()


class AppHeaderBar(QWidget):
    """Общая шапка приложения (на всех страницах)."""

    create_clicked = Signal()
    settings_clicked = Signal()
    logout_clicked = Signal()
    profile_clicked = Signal()

    def __init__(
        self,
        title: str = "Создание агента",
        subtitle: str = "Опишите задачу — система задаст вопросы и подготовит план",
        *,
        profile_name: str = "Пользователь",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("appHeaderBar")
        self._profile_name = profile_name

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        self._title_label = QLabel(title)
        self._title_label.setObjectName("hdrTitle")
        self._subtitle_label = QLabel(subtitle)
        self._subtitle_label.setObjectName("hdrSubtitle")
        self._subtitle_label.setWordWrap(True)
        left.addWidget(self._title_label)
        left.addWidget(self._subtitle_label)

        self.create_button = QPushButton("+ Создать агента")
        self.create_button.setObjectName("hdrCreate")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.clicked.connect(self.create_clicked.emit)

        bell = QLabel("🔔")
        bell.setObjectName("hdrBell")
        bell.setFixedWidth(28)
        bell.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._profile_block = QWidget()
        self._profile_block.setObjectName("hdrProfileBlock")
        self._profile_block.setCursor(Qt.CursorShape.PointingHandCursor)
        profile_layout = QHBoxLayout(self._profile_block)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(10)

        self.avatar = QLabel(_initials(profile_name))
        self.avatar.setObjectName("hdrAvatar")
        self.avatar.setFixedSize(34, 34)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name = QLabel(profile_name)
        self.name.setObjectName("hdrProfile")

        profile_layout.addWidget(self.avatar)
        profile_layout.addWidget(self.name)
        self._profile_block.mousePressEvent = self._on_profile_press  # type: ignore[method-assign]

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        right.addWidget(self.create_button)
        right.addWidget(bell)
        right.addWidget(self._profile_block)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(16)
        root.addLayout(left, 1)
        root.addLayout(right, 0)

        self.setStyleSheet(
            "#appHeaderBar { background: transparent; }"
            f"#hdrTitle {{ color: {_TEXT}; font-size: 20px; font-weight: 800; }}"
            f"#hdrSubtitle {{ color: {_MUTED}; font-size: 12px; }}"
            f"#hdrCreate {{ background: {_ACCENT}; color: white; border: none;"
            "border-radius: 10px; padding: 8px 14px; font-size: 12px; font-weight: 700; }"
            "#hdrCreate:hover { background: #6a68e0; }"
            f"#hdrBell {{ color: {_MUTED}; font-size: 14px; }}"
            "#hdrAvatar { background: #2a2a4a; color: #c8cbff; border-radius: 17px;"
            "font-size: 11px; font-weight: 700; }"
            f"#hdrProfile {{ color: {_TEXT}; font-size: 12px; font-weight: 600; }}"
        )

        self._menu = _ProfileMenuPopup(self)
        self._menu.settings_clicked.connect(self._emit_settings)
        self._menu.logout_clicked.connect(self.logout_clicked.emit)

    def set_chrome(
        self,
        title: str,
        subtitle: str = "",
        *,
        show_create: bool = True,
    ) -> None:
        """Обновить заголовок/подзаголовок текущей страницы."""
        self._title_label.setText(title)
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle.strip()))
        self.create_button.setVisible(show_create)

    def _emit_settings(self) -> None:
        self.settings_clicked.emit()
        self.profile_clicked.emit()

    def _on_profile_press(self, _event) -> None:
        self._show_profile_menu()

    def _show_profile_menu(self) -> None:
        """Открыть меню сразу под блоком ФИО, в пределах текущего экрана."""
        if self._menu.isVisible():
            self._menu.hide()
            return

        anchor = self._profile_block
        # Глобальная точка под левым краем блока профиля.
        below_left = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        menu_w = self._menu.width()
        menu_h = self._menu.sizeHint().height()

        # Правый край меню = правый край блока ФИО.
        x = below_left.x() + anchor.width() - menu_w
        y = below_left.y()

        screen = QGuiApplication.screenAt(anchor.mapToGlobal(QPoint(0, 0)))
        if screen is None:
            screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left() + 8, min(x, geo.right() - menu_w - 8))
            if y + menu_h > geo.bottom() - 8:
                # Не хватает места снизу — открыть над ФИО.
                above = anchor.mapToGlobal(QPoint(0, -menu_h - 6))
                y = max(geo.top() + 8, above.y())
            y = max(geo.top() + 8, min(y, geo.bottom() - menu_h - 8))

        self._menu.move(x, y)
        self._menu.show()
        self._menu.raise_()

    def set_profile(self, name: str, avatar_bytes: bytes | None = None) -> None:
        """Обновить отображаемое имя и круглую аватарку."""
        self._profile_name = name
        self.name.setText(name)
        if avatar_bytes:
            pix = QPixmap()
            if pix.loadFromData(avatar_bytes):
                self.avatar.setPixmap(
                    pix.scaled(
                        34,
                        34,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.avatar.setText("")
                return
        self.avatar.setPixmap(QPixmap())
        self.avatar.setText(_initials(name))
