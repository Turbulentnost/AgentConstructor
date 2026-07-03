"""Общие helper-функции desktop UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem, QWidget


def open_local_path(path: str) -> None:
    """Открыть файл или папку в системном проводнике/приложении."""
    target = Path(path)
    if not target.exists():
        # Если конкретного файла нет, пробуем открыть его папку.
        target = target.parent
    if not target.exists():
        return
    if os.name == "nt":
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def collect_produced_files(state: object) -> list[str]:
    """Собрать пути к файлам, созданным/изменённым инструментами за запуск."""
    paths: list[str] = []
    for record in getattr(state, "tool_results", []) or []:
        output = getattr(record, "output_data", None) or {}
        candidate = output.get("path") if isinstance(output, dict) else None
        if candidate and candidate not in paths:
            paths.append(str(candidate))
    return paths


def build_file_links_html(paths: list[str], folder: str | None = None) -> str:
    """Сформировать HTML со ссылками на созданные файлы и папку агента."""
    if not paths and not folder:
        return ""
    parts: list[str] = []
    for path in paths:
        name = Path(path).name
        url = QUrl.fromLocalFile(path).toString()
        parts.append(f'📄 <a href="{url}">{name}</a>')
    if folder:
        folder_url = QUrl.fromLocalFile(folder).toString()
        parts.append(f'📂 <a href="{folder_url}">Открыть папку агента</a>')
    return "Файлы: " + " &nbsp;•&nbsp; ".join(parts)


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    """Показать информационное сообщение."""
    QMessageBox.information(parent, title, message)


def show_error(parent: QWidget | None, title: str, error: Exception | str) -> None:
    """Показать понятную ошибку без traceback."""
    QMessageBox.critical(parent, title, str(error))


def format_json_preview(data: Any, max_chars: int = 5000) -> str:
    """Сформировать компактный JSON preview с ограничением размера."""
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def safe_short_text(text: object, max_len: int = 300) -> str:
    """Вернуть короткий текст для таблиц."""
    value = "" if text is None else str(text)
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def set_table_rows(
    table: QTableWidget,
    rows: list[list[object]],
    headers: list[str],
) -> None:
    """Заполнить QTableWidget строками."""
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            table.setItem(
                row_index,
                column_index,
                QTableWidgetItem(safe_short_text(value)),
            )
    table.resizeColumnsToContents()

