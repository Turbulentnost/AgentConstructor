"""Правая панель «Параметры агента» на этапе планирования / публикации."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.app.core.agent_image_client import (
    AgentImageUploadError,
    fetch_image_bytes,
    upload_agent_image,
)
from agent_desktop_constructor.app.ui.helpers import show_error, show_info
from agent_desktop_constructor.app.ui.widgets.agent_avatar_widget import AgentAvatarWidget
from agent_desktop_constructor.core.models.agent_spec import AgentSpec

_CARD = "#161625"
_ACCENT = "#5856D6"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"
_CHIP = "#2a2a4a"

_SOURCE_LABELS = {
    "email": "Электронная почта",
    "mail": "Электронная почта",
    "outlook": "Электронная почта",
    "file": "Документы",
    "document": "Документы",
    "documents": "Документы",
    "excel": "Документы",
    "pdf": "Документы",
    "folder": "Папка",
    "path": "Папка",
}


class AgentCardPanel(QFrame):
    """Редактируемые параметры агента: аватар, название, описание, цель, теги."""

    save_draft_clicked = Signal()
    next_clicked = Signal()
    image_url_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("agentCardPanel")
        self.setMinimumWidth(380)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self._agent: AgentSpec | None = None
        self._attachment_names: list[str] = []
        self._image_url: str | None = None
        self._media_proxy_url: str | None = None

        header = QHBoxLayout()
        header.setSpacing(12)
        self._avatar = AgentAvatarWidget()
        self._avatar.upload_clicked.connect(self._pick_and_upload_image)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Параметры агента")
        title.setObjectName("acTitle")
        hint = QLabel("Заполняется автоматически")
        hint.setObjectName("acHint")
        title_col.addWidget(title)
        title_col.addWidget(hint)
        header.addWidget(self._avatar)
        header.addLayout(title_col, 1)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Название")
        self.name_edit.setObjectName("acField")

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Описание")
        self.description_edit.setObjectName("acField")
        self.description_edit.setFixedHeight(72)

        self.goal_edit = QTextEdit()
        self.goal_edit.setPlaceholderText("Цель")
        self.goal_edit.setObjectName("acField")
        self.goal_edit.setFixedHeight(64)

        self.tags_host = QWidget()
        self.tags_layout = QHBoxLayout(self.tags_host)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(6)
        self.tags_layout.addStretch(1)

        self.meta_label = QLabel("0 источников • 0 шагов")
        self.meta_label.setObjectName("acMeta")

        note = QLabel("Вы сможете изменить эти данные до публикации.")
        note.setObjectName("acNote")
        note.setWordWrap(True)

        self.draft_button = QPushButton("Сохранить черновик")
        self.draft_button.setObjectName("acDraft")
        self.draft_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.draft_button.clicked.connect(self.save_draft_clicked.emit)

        self.next_button = QPushButton("Далее: запустить тест →")
        self.next_button.setObjectName("acNext")
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self._field_label("Название"))
        layout.addWidget(self.name_edit)
        layout.addWidget(self._field_label("Описание"))
        layout.addWidget(self.description_edit)
        layout.addWidget(self._field_label("Цель"))
        layout.addWidget(self.goal_edit)
        layout.addWidget(self.tags_host)
        layout.addWidget(self.meta_label)
        layout.addStretch(1)
        layout.addWidget(note)
        layout.addWidget(self.draft_button)
        layout.addWidget(self.next_button)

        self.setStyleSheet(
            f"#agentCardPanel {{ background: {_CARD}; border: 1px solid #2a2a3d;"
            "border-radius: 16px; }"
            f"#acTitle {{ color: {_TEXT}; font-size: 14px; font-weight: 800; }}"
            f"#acHint {{ color: {_MUTED}; font-size: 11px; }}"
            f"#acLabel {{ color: {_MUTED}; font-size: 11px; font-weight: 600; }}"
            f"#acField {{ background: #0f0f1a; color: {_TEXT}; border: 1px solid #2a2a3d;"
            "border-radius: 8px; padding: 6px 8px; font-size: 12px; }"
            f"#acMeta {{ color: {_MUTED}; font-size: 11px; }}"
            f"#acNote {{ color: {_MUTED}; font-size: 11px; }}"
            f"#acDraft {{ background: transparent; color: {_ACCENT}; border: none;"
            "text-align: left; font-size: 12px; font-weight: 600; padding: 4px 0; }"
            f"#acNext {{ background: {_ACCENT}; color: white; border: none;"
            "border-radius: 10px; padding: 10px 12px; font-size: 12px; font-weight: 700; }"
            "#acNext:disabled { background: #2a2a3d; color: #6b7088; }"
            "#acNext:hover:!disabled { background: #6a68e0; }"
            f"#acChip {{ background: {_CHIP}; color: #b8bcff; border-radius: 10px;"
            "padding: 4px 10px; font-size: 11px; font-weight: 600; }"
        )

    def set_media_proxy_url(self, url: str | None) -> None:
        """URL LLM-прокси, через который загружаются изображения в MinIO."""
        self._media_proxy_url = (url or "").strip() or None

    def current_image_url(self) -> str | None:
        """Текущий URL изображения агента."""
        return self._image_url

    def set_next_label(self, text: str) -> None:
        """Подпись основной кнопки (зависит от шага мастера)."""
        self.next_button.setText(text)

    def set_next_enabled(self, enabled: bool) -> None:
        """Разрешить переход к следующему шагу."""
        self.next_button.setEnabled(enabled)

    def bind_agent_spec(
        self,
        agent: AgentSpec | None,
        attachment_paths: list[str] | None = None,
    ) -> None:
        """Заполнить поля из AgentSpec и списка вложений."""
        self._agent = agent
        self._attachment_names = [
            Path(path).name for path in (attachment_paths or []) if path
        ]
        if agent is None:
            self.name_edit.clear()
            self.description_edit.clear()
            self.goal_edit.clear()
            self._image_url = None
            self._avatar.set_placeholder()
            self._set_tags([])
            self.meta_label.setText("0 источников • 0 шагов")
            self.next_button.setEnabled(False)
            return

        self.name_edit.setText(agent.name or "")
        self.description_edit.setPlainText(agent.description or "")
        self.goal_edit.setPlainText(agent.goal.main_goal if agent.goal else "")
        self._image_url = agent.image_url
        self._load_avatar_preview(agent.image_url)
        tags = self._collect_tags(agent)
        self._set_tags(tags)
        sources = max(len(agent.data_requirements), len(self._attachment_names))
        steps = len(agent.graph_nodes)
        self.meta_label.setText(f"{sources} источников • {steps} шагов")
        self.next_button.setEnabled(True)

    def apply_edits_to_spec(self, agent: AgentSpec) -> AgentSpec:
        """Применить правки полей карточки к копии AgentSpec."""
        name = self.name_edit.text().strip() or agent.name
        description = self.description_edit.toPlainText().strip() or agent.description
        goal_text = self.goal_edit.toPlainText().strip() or agent.goal.main_goal
        goal = agent.goal.model_copy(update={"main_goal": goal_text})
        return agent.model_copy(
            update={
                "name": name,
                "description": description,
                "goal": goal,
                "short_description": agent.short_description or goal_text[:200],
                "image_url": self._image_url,
            }
        )

    def current_name(self) -> str:
        """Текущее название из поля ввода."""
        return self.name_edit.text().strip()

    def _pick_and_upload_image(self) -> None:
        if self._agent is None:
            show_error(
                self,
                "Нет агента",
                "Сначала опишите задачу и дождитесь построения плана.",
            )
            return
        if not self._media_proxy_url:
            show_error(
                self,
                "Нет прокси",
                "В настройках не задан llm_proxy_url для загрузки изображений.",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Изображение агента",
            "",
            "Изображения (*.png *.jpg *.jpeg *.webp *.gif);;Все файлы (*.*)",
        )
        if not path:
            return

        local_preview = QPixmap(path)
        if not local_preview.isNull():
            self._avatar.set_pixmap(local_preview)

        try:
            image_url = upload_agent_image(
                self._media_proxy_url,
                self._agent.agent_id,
                path,
            )
        except AgentImageUploadError as exc:
            self._load_avatar_preview(self._image_url)
            show_error(self, "Не удалось загрузить изображение", str(exc))
            return

        self._image_url = image_url
        self._load_avatar_preview(image_url)
        self.image_url_changed.emit(image_url)
        show_info(self, "Изображение сохранено", "Аватар агента загружен в MinIO.")

    def _load_avatar_preview(self, image_url: str | None) -> None:
        if not image_url:
            self._avatar.set_placeholder()
            return
        try:
            payload = fetch_image_bytes(image_url)
        except AgentImageUploadError:
            self._avatar.set_placeholder()
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(payload):
            self._avatar.set_pixmap(pixmap)
        else:
            self._avatar.set_placeholder()

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("acLabel")
        return label

    def _collect_tags(self, agent: AgentSpec) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()

        def add(label: str) -> None:
            key = label.casefold()
            if key and key not in seen:
                seen.add(key)
                tags.append(label)

        for req in agent.data_requirements:
            raw = (req.source_type or "").strip().lower()
            add(_SOURCE_LABELS.get(raw, req.source_type or req.name))
        for tool in agent.tools:
            if not tool.allowed or not tool.tool_name:
                continue
            category = tool.tool_name.split(".", 1)[0].lower()
            if category in _SOURCE_LABELS:
                add(_SOURCE_LABELS[category])
        if self._attachment_names:
            add("Документы")
            first = self._attachment_names[0]
            if first.lower().endswith((".xlsx", ".xls", ".csv", ".docx", ".pdf")):
                add(first)
        return tags[:6]

    def _set_tags(self, tags: list[str]) -> None:
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for tag in tags:
            chip = QLabel(tag)
            chip.setObjectName("acChip")
            self.tags_layout.addWidget(chip)
        self.tags_layout.addStretch(1)
