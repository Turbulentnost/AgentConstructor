"""Общие компоненты нижней панели ввода (composer) для этапов мастера."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton

REF_PANEL = "#08172a"
REF_BORDER = "#16304f"

COMPOSER_ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"
COMPOSER_ICON_FILES: dict[str, tuple[str, str]] = {
    "attach": ("paperclip-default.svg", "paperclip-active.svg"),
    "database": ("server-default.svg", "server-active.svg"),
}

COMPOSER_PANEL_STYLESHEET = f"""
#composerPanel {{
    background:{REF_PANEL}; border:1px solid {REF_BORDER};
    border-radius:14px;
}}
#requestEdit {{
    background:transparent; color:#cbd5e1; border:none;
    padding:0; margin:0; font-size:13px; line-height:1.2;
    selection-background-color:#2f7cff;
}}
#composerIconButton {{
    background:#0c1828; color:#94a3b8; border:1px solid #1a2a40;
    border-radius:7px;
}}
#composerIconButton:hover {{ background:#132238; border-color:#2a4060; }}
#composerSendButton {{
    background:#2f80ff; color:#ffffff; border:none;
    border-radius:9px; padding:4px 14px; font-size:12px; font-weight:700;
}}
#composerSendButton:hover {{ background:#3d8bff; }}
#composerSendButton:disabled {{ background:#1e3a5f; color:#b8ccf5; }}
#launchSplit {{ background:#2f80ff; border-radius:9px; }}
#launchSplitMain {{
    background:transparent; color:#ffffff; border:none;
    padding:4px 10px; font-size:12px; font-weight:700;
}}
#launchSplitMain:hover {{ background:rgba(255,255,255,0.06); }}
#launchSplitMain:disabled {{ color:#b8ccf5; }}
#launchSplitMenu {{
    background:transparent; color:#ffffff; border:none;
    border-top-right-radius:9px; border-bottom-right-radius:9px;
}}
#launchSplitMenu::menu-indicator {{ width:0px; height:0px; border:none; }}
#launchSplitDivider {{ background:rgba(0,0,0,0.22); min-width:1px; max-width:1px; }}
#launchSplitMenu:hover {{ background:rgba(255,255,255,0.08); }}
#launchSplitStop {{
    background:#5a2630; color:#ffc4ce; border:1px solid #8b3342;
    border-radius:7px; padding:8px 12px; font-size:12px; font-weight:700;
}}
#attachLabel {{ color:#93c5fd; font-size:12px; }}
#attachClearButton {{
    background:transparent; color:#94a3b8; border:1px solid #1a2a40;
    border-radius:6px; padding:3px 8px; font-size:11px;
}}
#attachClearButton:hover {{ color:#e2e8f0; border-color:#2a4060; }}
"""


class ComposerIconButton(QPushButton):
    """Квадратная кнопка с SVG-иконкой для нижней панели composer."""

    _ICON_SIZE = 18
    _svg_cache: dict[str, tuple[QSvgRenderer, QSvgRenderer]] = {}

    def __init__(self, kind: str, tooltip: str = "", parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setText("")
        self.setObjectName("composerIconButton")
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(30, 30)

    @classmethod
    def _svg_renderers(cls, kind: str) -> tuple[QSvgRenderer, QSvgRenderer] | None:
        files = COMPOSER_ICON_FILES.get(kind)
        if files is None:
            return None
        if kind not in cls._svg_cache:
            default_path = COMPOSER_ICONS_DIR / files[0]
            active_path = COMPOSER_ICONS_DIR / files[1]
            cls._svg_cache[kind] = (
                QSvgRenderer(str(default_path)),
                QSvgRenderer(str(active_path)),
            )
        return cls._svg_cache[kind]

    def _use_active_icon(self) -> bool:
        return self.underMouse() or self.isDown()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        renderers = self._svg_renderers(self._kind)
        if renderers is not None:
            renderer = renderers[1] if self._use_active_icon() else renderers[0]
            if renderer.isValid():
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                offset = (self.width() - self._ICON_SIZE) / 2
                renderer.render(
                    painter,
                    QRectF(offset, offset, self._ICON_SIZE, self._ICON_SIZE),
                )
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#94a3b8")
        pen = QPen(color, 1.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._kind == "grid":
            painter.drawRect(QRectF(7, 7, 7, 7))
            painter.drawRect(QRectF(16, 7, 7, 7))
            painter.drawRect(QRectF(7, 16, 7, 7))
            painter.drawRect(QRectF(16, 16, 7, 7))
        else:
            painter.drawLine(QPointF(10, 10), QPointF(8, 10))
            painter.drawLine(QPointF(8, 10), QPointF(8, 20))
            painter.drawLine(QPointF(8, 20), QPointF(10, 20))
            painter.drawLine(QPointF(20, 10), QPointF(22, 10))
            painter.drawLine(QPointF(22, 10), QPointF(22, 20))
            painter.drawLine(QPointF(22, 20), QPointF(20, 20))
