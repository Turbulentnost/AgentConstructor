"""Верхняя панель конструктора: заголовок, кнопка создать, профиль."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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


class AppHeaderBar(QWidget):
    """Шапка страницы «Создание агента» по референсу."""

    create_clicked = Signal()

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

        avatar = QLabel("МД")
        avatar.setObjectName("hdrAvatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name = QLabel(profile_name)
        name.setObjectName("hdrProfile")

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        right.addWidget(self.create_button)
        right.addWidget(bell)
        right.addWidget(avatar)
        right.addWidget(name)

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
