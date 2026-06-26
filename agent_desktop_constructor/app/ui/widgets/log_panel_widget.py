"""Панель сообщений desktop UI."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class LogPanelWidget(QWidget):
    """Простой read-only журнал сообщений UI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Создать панель журнала."""
        super().__init__(parent)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.clear_button = QPushButton("Очистить")
        self.clear_button.clicked.connect(self.text_edit.clear)

        layout = QVBoxLayout(self)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.clear_button)

    def append_message(self, message: str) -> None:
        """Добавить сообщение в журнал."""
        self.text_edit.append(message)

