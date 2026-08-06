"""Горизонтальный stepper мастера: Планирование → Тестирование → Workflow → Публикация."""

from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

_ACCENT = "#5856D6"
_MUTED = "#6b7088"
_TEXT = "#e8eaf2"
_DONE = "#3dd68c"


class WizardStep(IntEnum):
    """Индексы шагов мастера конструктора."""

    PLANNING = 0
    TESTING = 1
    WORKFLOW = 2
    PUBLICATION = 3


WIZARD_STEPS: tuple[tuple[WizardStep, str], ...] = (
    (WizardStep.PLANNING, "Планирование"),
    (WizardStep.TESTING, "Тестирование"),
    (WizardStep.WORKFLOW, "Workflow"),
    (WizardStep.PUBLICATION, "Публикация"),
)


class WizardStepper(QWidget):
    """Нумерованная лента шагов; клик по пройденному шагу эмитит сигнал."""

    step_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = WizardStep.PLANNING
        self._max_reached = WizardStep.PLANNING
        self._labels: list[QLabel] = []
        self._circles: list[QLabel] = []

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 8)
        row.setSpacing(0)

        for index, (_step, title) in enumerate(WIZARD_STEPS):
            if index > 0:
                line = QFrame()
                line.setFixedHeight(2)
                line.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Fixed,
                )
                line.setStyleSheet("background: #2a2a3d; border: none;")
                row.addWidget(line, 1)

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(4, 0, 4, 0)
            cell_layout.setSpacing(8)

            circle = QLabel(str(index + 1))
            circle.setFixedSize(28, 28)
            circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            circle.setCursor(Qt.CursorShape.PointingHandCursor)
            circle.mousePressEvent = (  # type: ignore[method-assign]
                lambda event, i=index: self._on_circle_click(i)
            )

            label = QLabel(title)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.mousePressEvent = (  # type: ignore[method-assign]
                lambda event, i=index: self._on_circle_click(i)
            )

            cell_layout.addWidget(circle)
            cell_layout.addWidget(label)
            row.addWidget(cell, 0)

            self._circles.append(circle)
            self._labels.append(label)

        self._apply_styles()

    def current_step(self) -> WizardStep:
        """Текущий активный шаг."""
        return self._current

    def max_reached(self) -> WizardStep:
        """Максимальный достигнутый шаг (для gating кликов назад/вперёд)."""
        return self._max_reached

    def set_step(self, step: WizardStep | int, *, unlock: bool = False) -> None:
        """Установить активный шаг; при unlock расширить max_reached."""
        value = WizardStep(int(step))
        self._current = value
        if unlock or value > self._max_reached:
            self._max_reached = value
        self._apply_styles()

    def unlock_through(self, step: WizardStep | int) -> None:
        """Разрешить переход до указанного шага включительно."""
        value = WizardStep(int(step))
        if value > self._max_reached:
            self._max_reached = value
        self._apply_styles()

    def reset(self) -> None:
        """Сбросить мастер на первый шаг."""
        self._current = WizardStep.PLANNING
        self._max_reached = WizardStep.PLANNING
        self._apply_styles()

    def _on_circle_click(self, index: int) -> None:
        if index <= int(self._max_reached):
            self.step_clicked.emit(index)

    def _apply_styles(self) -> None:
        for index, (circle, label) in enumerate(zip(self._circles, self._labels)):
            if index < int(self._current):
                circle.setStyleSheet(
                    f"background:{_DONE}; color:#0b0b14; border-radius:14px;"
                    "font-size:12px; font-weight:800;"
                )
                label.setStyleSheet(f"color:{_TEXT}; font-size:12px; font-weight:600;")
            elif index == int(self._current):
                circle.setStyleSheet(
                    f"background:{_ACCENT}; color:white; border-radius:14px;"
                    "font-size:12px; font-weight:800;"
                )
                label.setStyleSheet(f"color:{_TEXT}; font-size:12px; font-weight:700;")
            else:
                circle.setStyleSheet(
                    "background:#1c1c2e; color:#6b7088; border-radius:14px;"
                    "font-size:12px; font-weight:700;"
                )
                label.setStyleSheet(f"color:{_MUTED}; font-size:12px; font-weight:600;")
