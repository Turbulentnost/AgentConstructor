"""Верхняя панель конструктора: заголовок, кнопка создать, профиль."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ACCENT = "#5856D6"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    return "".join(p[0] for p in parts[:2]).upper()


class AppHeaderBar(QWidget):
    """Шапка страницы «Создание агента» по референсу."""

    create_clicked = Signal()
    profile_clicked = Signal()

    def __init__(
        self,
        title: str = "Создание агента",
        subtitle: str = "Опишите задачу — система задаст вопросы и подготовит план",
        *,
        profile_name: str = "Мангасарян Давид Каренович",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("appHeaderBar")
        self._profile_name = profile_name

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("hdrTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("hdrSubtitle")
        subtitle_label.setWordWrap(True)
        left.addWidget(title_label)
        left.addWidget(subtitle_label)

        self.create_button = QPushButton("+ Создать агента")
        self.create_button.setObjectName("hdrCreate")
        self.create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.clicked.connect(self.create_clicked.emit)

        bell = QLabel("🔔")
        bell.setObjectName("hdrBell")
        bell.setFixedWidth(28)
        bell.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.avatar = QLabel(_initials(profile_name))
        self.avatar.setObjectName("hdrAvatar")
        self.avatar.setFixedSize(34, 34)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.avatar.mousePressEvent = self._on_profile_press  # type: ignore[method-assign]

        self.name = QLabel(profile_name)
        self.name.setObjectName("hdrProfile")
        self.name.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name.mousePressEvent = self._on_profile_press  # type: ignore[method-assign]

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        right.addWidget(self.create_button)
        right.addWidget(bell)
        right.addWidget(self.avatar)
        right.addWidget(self.name)

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

    def _on_profile_press(self, _event) -> None:
        self.profile_clicked.emit()

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
