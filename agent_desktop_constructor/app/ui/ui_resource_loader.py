"""Загрузка PNG/SVG ресурсов для UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer


def load_scaled_pixmap(path: Path, width: int, height: int) -> QPixmap:
    """Загрузить PNG или отрендерить SVG в pixmap заданного размера."""
    if not path.exists():
        return QPixmap()

    if path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(path))
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        if renderer.isValid():
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
        return pixmap

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def load_square_icon(path: Path, size: int) -> QPixmap:
    """Квадратная иконка с сохранением пропорций."""
    return load_scaled_pixmap(path, size, size)
