"""Аватар агента: серый placeholder, камера при наведении, загрузка по клику."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

_BOX = 56
_CAMERA_H = 28
_GRAY = "#4a4e5e"
_CAMERA_BG = "rgba(11, 11, 20, 0.82)"


class AgentAvatarWidget(QFrame):
    """Квадратный аватар с анимацией камеры при наведении."""

    upload_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("agentAvatar")
        self.setFixedSize(_BOX, _BOX)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._preview = QLabel(self)
        self._preview.setObjectName("agentAvatarPreview")
        self._preview.setGeometry(0, 0, _BOX, _BOX)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setScaledContents(True)

        self._camera = QPushButton("📷", self)
        self._camera.setObjectName("agentAvatarCamera")
        self._camera.setToolTip("Загрузить изображение агента")
        self._camera.setCursor(Qt.CursorShape.PointingHandCursor)
        self._camera.setFixedSize(_BOX, _CAMERA_H)
        self._camera.move(0, _BOX)
        self._camera.clicked.connect(self.upload_clicked.emit)

        self._hover_anim = QPropertyAnimation(self._camera, b"pos", self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.set_placeholder()
        self.setStyleSheet(
            f"#agentAvatar {{ background: {_GRAY}; border-radius: 12px; }}"
            "#agentAvatarPreview { background: transparent; border-radius: 12px; }"
            f"#agentAvatarCamera {{ background: {_CAMERA_BG}; color: white; border: none;"
            "border-bottom-left-radius: 12px; border-bottom-right-radius: 12px;"
            "font-size: 16px; }}"
            "#agentAvatarCamera:hover { background: rgba(88, 86, 214, 0.92); }"
        )

    def set_placeholder(self) -> None:
        """Серый блок по умолчанию без изображения."""
        self._preview.clear()
        self._preview.setPixmap(QPixmap())

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Показать локальный или загруженный pixmap."""
        if pixmap.isNull():
            self.set_placeholder()
            return
        self._preview.setPixmap(
            pixmap.scaled(
                _BOX,
                _BOX,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_camera(show=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_camera(show=False)
        super().leaveEvent(event)

    def _animate_camera(self, *, show: bool) -> None:
        self._hover_anim.stop()
        hidden = QPoint(0, _BOX)
        visible = QPoint(0, _BOX - _CAMERA_H)
        self._hover_anim.setStartValue(visible if not show else hidden)
        self._hover_anim.setEndValue(visible if show else hidden)
        self._hover_anim.start()
