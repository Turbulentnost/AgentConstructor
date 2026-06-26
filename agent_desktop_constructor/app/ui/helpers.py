"""Общие helper-функции desktop UI."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem, QWidget


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

