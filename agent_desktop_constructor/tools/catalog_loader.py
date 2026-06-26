"""Загрузка JSON-каталога доступных инструментов."""

import json
from pathlib import Path

from pydantic import ValidationError

from agent_desktop_constructor.tools.catalog import ToolsCatalog


DEFAULT_TOOLS_CATALOG_PATH = Path(__file__).with_name("default_tools_catalog.json")


def load_tools_catalog(path: Path | str | None = None) -> ToolsCatalog:
    """Загрузить и провалидировать каталог инструментов из JSON-файла."""
    catalog_path = Path(path) if path is not None else DEFAULT_TOOLS_CATALOG_PATH
    if not catalog_path.exists():
        raise ValueError(f"Файл каталога инструментов не найден: {catalog_path}")

    try:
        raw_text = catalog_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать каталог инструментов: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON каталога инструментов: {exc.msg}") from exc

    try:
        return ToolsCatalog.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Каталог инструментов не прошёл валидацию: {exc}") from exc
