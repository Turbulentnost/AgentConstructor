"""Заглушки страниц Главная и Аналитика в стиле референса."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_BG = "#0B0B14"
_CARD = "#161625"
_ACCENT = "#5856D6"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"


class PlaceholderPage(QWidget):
    """Общая тёмная страница-заглушка с заголовком и описанием."""

    primary_clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        primary_label: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("placeholderPage")
        self.setStyleSheet(
            f"#placeholderPage {{ background: {_BG}; }}"
            f"#phCard {{ background: {_CARD}; border: 1px solid #2a2a3d;"
            f"border-radius: 16px; }}"
            f"#phTitle {{ color: {_TEXT}; font-size: 22px; font-weight: 800; }}"
            f"#phSubtitle {{ color: {_MUTED}; font-size: 13px; }}"
            f"#phPrimary {{ background: {_ACCENT}; color: white; border: none;"
            f"border-radius: 12px; padding: 12px 20px; font-size: 13px;"
            f"font-weight: 700; }}"
            "#phPrimary:hover { background: #6a68e0; }"
        )

        card = QFrame()
        card.setObjectName("phCard")
        card.setMaximumWidth(520)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("phTitle")
        title_label.setWordWrap(True)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("phSubtitle")
        subtitle_label.setWordWrap(True)
        card_layout.addWidget(title_label)
        card_layout.addWidget(subtitle_label)

        if primary_label:
            button = QPushButton(primary_label)
            button.setObjectName("phPrimary")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(self.primary_clicked.emit)
            card_layout.addSpacing(8)
            card_layout.addWidget(button)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.addStretch(1)
        root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(2)


class HomePlaceholderWidget(PlaceholderPage):
    """Главная: краткий hero и переход в конструктор."""

    go_to_constructor = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Главная",
            "Опишите задачу — система задаст вопросы, подготовит план "
            "и сохранит workflow для повторных запусков.",
            primary_label="Перейти к конструктору",
            parent=parent,
        )
        self.primary_clicked.connect(self.go_to_constructor.emit)


class AnalyticsPlaceholderWidget(PlaceholderPage):
    """Аналитика: раздел в разработке."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Аналитика",
            "Раздел в разработке. Здесь появятся метрики запусков "
            "и качество работы агентов.",
            parent=parent,
        )
