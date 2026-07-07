"""Переиспользуемая панель участия человека (вопрос/просьба + варианты).

Показывает вопрос агента, план его дальнейших действий, варианты ответа
радиокнопками и всегда — поле «Свой вариант ответа». По кнопке «Продолжить»
эмитит выбранный ответ. Используется на экранах создания и каталога агентов.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class HumanInteractionPanel(QFrame):
    """Панель, останавливающая работу до ответа/действия человека."""

    continue_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Собрать разметку панели участия человека."""
        super().__init__(parent)
        self.setObjectName("humanPanel")
        self.setStyleSheet(
            "#humanPanel { background:#241d12; border:1px solid #8a6d15;"
            "border-radius:10px; }"
            "QLabel { color:#f0e6cf; }"
            "QRadioButton { color:#f0e6cf; font-size:12px; padding:2px 0; }"
            "QLineEdit { background:#12141a; color:#e6e9ef; border:1px solid #4a4030;"
            "border-radius:6px; padding:6px; font-size:12px; }"
        )
        self._radios: list[tuple[QRadioButton, str | None]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        # Панель не должна сжиматься меньше, чем нужно её содержимому, иначе
        # вопрос и варианты накладываются друг на друга.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        self.title_label = QLabel("Агенту требуется ваше участие")
        self.title_label.setStyleSheet(
            "font-size:14px; font-weight:700; color:#ffdf9e;"
        )
        layout.addWidget(self.title_label)

        self.question_label = QLabel()
        self.question_label.setWordWrap(True)
        self.question_label.setStyleSheet("font-size:13px; color:#f4ecd8;")
        layout.addWidget(self.question_label)

        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        self.plan_label.setStyleSheet("font-size:11px; color:#c9b98f;")
        layout.addWidget(self.plan_label)

        self._options_host = QWidget()
        self._options_layout = QVBoxLayout(self._options_host)
        self._options_layout.setContentsMargins(0, 0, 0, 0)
        self._options_layout.setSpacing(4)
        self._options_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Если вариантов много — они прокручиваются внутри панели, а не
        # наезжают друг на друга и не растягивают экран.
        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.Shape.NoFrame)
        options_scroll.setMaximumHeight(220)
        options_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        options_scroll.setStyleSheet("QScrollArea { background:transparent; }")
        options_scroll.setWidget(self._options_host)
        layout.addWidget(options_scroll)

        self._button_group = QButtonGroup(self)

        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("Свой вариант ответа…")
        layout.addWidget(self.custom_edit)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.continue_button = QPushButton("Продолжить")
        self.continue_button.setStyleSheet(
            "QPushButton { background:#1f7a3d; color:#ffffff; border:none;"
            "border-radius:8px; padding:9px 16px; font-size:12px; font-weight:700; }"
            "QPushButton:hover { background:#248c47; }"
            "QPushButton:disabled { background:#274a34; color:#8bb59a; }"
        )
        self.continue_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_button.clicked.connect(self._on_continue_clicked)
        actions.addWidget(self.continue_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.setVisible(False)

    def prompt(
        self,
        question: str,
        options: list[str],
        plan: str | None = None,
    ) -> None:
        """Показать вопрос/просьбу с вариантами и полем свободного ответа."""
        self.question_label.setText(question)
        if plan:
            self.plan_label.setText(f"После вашего ответа агент планирует: {plan}")
            self.plan_label.setVisible(True)
        else:
            self.plan_label.setVisible(False)
        self._populate_options(options or ["Готово, продолжить"])
        self.custom_edit.clear()
        self.continue_button.setEnabled(True)
        self.setVisible(True)

    def hide_panel(self) -> None:
        """Скрыть панель."""
        self.setVisible(False)

    def selected_answer(self) -> str | None:
        """Вернуть выбранный ответ (вариант или свой текст)."""
        for radio, option in self._radios:
            if not radio.isChecked():
                continue
            if option is None:
                return self.custom_edit.text().strip()
            return option
        return self.custom_edit.text().strip() or None

    def _populate_options(self, options: list[str]) -> None:
        """Перестроить радиокнопки вариантов + «Свой вариант ответа»."""
        for radio, _ in self._radios:
            self._button_group.removeButton(radio)
            radio.setParent(None)
            radio.deleteLater()
        self._radios = []
        while self._options_layout.count():
            item = self._options_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)

        for index, option in enumerate(options):
            radio = self._add_option_row(option)
            self._radios.append((radio, option))
            if index == 0:
                radio.setChecked(True)

        custom_radio = self._add_option_row("Свой вариант ответа")
        self._radios.append((custom_radio, None))
        custom_radio.toggled.connect(self._on_custom_toggled)

    def _add_option_row(self, option: str) -> QRadioButton:
        """Добавить вариант: радиокнопка + переносимый по словам текст."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        radio = QRadioButton()
        self._button_group.addButton(radio)
        label = QLabel(option)
        label.setWordWrap(True)
        label.setStyleSheet("color:#f0e6cf; font-size:12px;")
        label.mousePressEvent = lambda _event, r=radio: r.setChecked(True)
        row_layout.addWidget(radio, 0, Qt.AlignmentFlag.AlignTop)
        row_layout.addWidget(label, 1)
        self._options_layout.addWidget(row)
        return radio

    def _on_custom_toggled(self, checked: bool) -> None:
        """Сфокусировать поле ввода при выборе своего варианта."""
        if checked:
            self.custom_edit.setFocus()

    def _on_continue_clicked(self) -> None:
        """Эмитировать выбранный ответ, если он есть."""
        answer = self.selected_answer()
        if not answer:
            return
        self.continue_button.setEnabled(False)
        self.continue_requested.emit(answer)
