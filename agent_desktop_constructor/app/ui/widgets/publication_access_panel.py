"""Выбор режима доступа при публикации агента."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

VISIBILITY_PRIVATE = "private"
VISIBILITY_DEPARTMENT = "department"
VISIBILITY_ALL = "all"
VISIBILITY_SELECTED = "selected"


class PublicationAccessPanel(QFrame):
    """Радиокнопки visibility + чекбоксы отделов для selected."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("publicationAccessPanel")
        self._department_boxes: list[QCheckBox] = []

        title = QLabel("Доступ к агенту")
        title.setStyleSheet("color:#e8eaf2; font-size:14px; font-weight:700;")
        hint = QLabel(
            "Приватный — только вы. Отдел — ваш отдел. "
            "Все — любой пользователь. Выбранные — отмеченные отделы."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8a8fa3; font-size:12px;")

        self._group = QButtonGroup(self)
        self.radio_private = QRadioButton("Приватный (только я)")
        self.radio_department = QRadioButton("Мой отдел")
        self.radio_all = QRadioButton("Все отделы")
        self.radio_selected = QRadioButton("Выбранные отделы")
        for index, radio in enumerate(
            (
                self.radio_private,
                self.radio_department,
                self.radio_all,
                self.radio_selected,
            )
        ):
            self._group.addButton(radio, index)
            radio.setStyleSheet("color:#d8e0ee; font-size:13px;")
        self.radio_private.setChecked(True)

        self._departments_label = QLabel("Отделы:")
        self._departments_label.setStyleSheet("color:#9aa0ac; font-size:12px;")
        self._departments_host = QWidget()
        self._departments_layout = QVBoxLayout(self._departments_host)
        self._departments_layout.setContentsMargins(0, 0, 0, 0)
        self._departments_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._departments_host)
        scroll.setFixedHeight(140)
        scroll.setStyleSheet(
            "QScrollArea { border:1px solid #2b2f3a; border-radius:8px; background:#12141c; }"
        )
        self._dept_scroll = scroll

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.radio_private)
        layout.addWidget(self.radio_department)
        layout.addWidget(self.radio_all)
        layout.addWidget(self.radio_selected)
        layout.addWidget(self._departments_label)
        layout.addWidget(scroll)

        self.radio_selected.toggled.connect(self._sync_departments_enabled)
        self._sync_departments_enabled(False)
        self.setStyleSheet(
            "#publicationAccessPanel {"
            "background:#161625; border:1px solid #2b2f3a; border-radius:12px;"
            "}"
        )

    def set_departments(self, departments: list[str]) -> None:
        """Заполнить список отделов для режима selected."""
        while self._departments_layout.count():
            item = self._departments_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._department_boxes.clear()
        for name in departments:
            box = QCheckBox(name)
            box.setStyleSheet("color:#d8e0ee; font-size:12px;")
            self._departments_layout.addWidget(box)
            self._department_boxes.append(box)
        if not departments:
            empty = QLabel("Список отделов пуст (синхронизация пользователей).")
            empty.setStyleSheet("color:#8a8fa3; font-size:12px;")
            self._departments_layout.addWidget(empty)
        self._departments_layout.addStretch(1)
        self._sync_departments_enabled(self.radio_selected.isChecked())

    def visibility(self) -> str:
        if self.radio_department.isChecked():
            return VISIBILITY_DEPARTMENT
        if self.radio_all.isChecked():
            return VISIBILITY_ALL
        if self.radio_selected.isChecked():
            return VISIBILITY_SELECTED
        return VISIBILITY_PRIVATE

    def selected_departments(self) -> list[str]:
        return [
            box.text().strip()
            for box in self._department_boxes
            if box.isChecked() and box.text().strip()
        ]

    def _sync_departments_enabled(self, enabled: bool) -> None:
        self._dept_scroll.setEnabled(enabled)
        self._departments_label.setEnabled(enabled)
        for box in self._department_boxes:
            box.setEnabled(enabled)
