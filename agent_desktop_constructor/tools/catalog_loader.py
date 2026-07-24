"""Загрузка JSON-каталога доступных инструментов."""

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from agent_desktop_constructor.tools.catalog import ToolsCatalog


DEFAULT_TOOLS_CATALOG_PATH = Path(__file__).with_name("default_tools_catalog.json")


def load_tools_catalog(path: Path | str | None = None) -> ToolsCatalog:
    """Загрузить и провалидировать каталог инструментов из JSON-файла."""
    catalog_path = _resolve_catalog_path(Path(path) if path is not None else None)

    try:
        raw_text = catalog_path.read_text(encoding="utf-8-sig")
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


def _resolve_catalog_path(explicit_path: Path | None = None) -> Path:
    """Найти JSON-каталог в source/frozen layout-ах PyInstaller.

    В one-folder сборке PyInstaller файлы данных обычно лежат в ``_internal``.
    При переносе exe между папками/сетевыми шарами layout иногда отличается, а
    старый код проверял только путь рядом с ``catalog_loader.py``. Здесь мы
    перебираем несколько безопасных кандидатов и даём понятную диагностику.
    """
    candidates = [explicit_path] if explicit_path is not None else _catalog_candidates()
    checked: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        checked.append(candidate)
        if candidate.exists():
            return candidate
    checked_text = "\n- ".join(str(path) for path in checked)
    raise ValueError(
        "Файл каталога инструментов не найден. Проверенные пути:\n- "
        f"{checked_text}"
    )


def _catalog_candidates() -> list[Path]:
    """Вернуть кандидаты расположения default_tools_catalog.json."""
    relative = Path("agent_desktop_constructor") / "tools" / "default_tools_catalog.json"
    candidates = [DEFAULT_TOOLS_CATALOG_PATH]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "_internal" / relative,
                exe_dir / relative,
                exe_dir / "default_tools_catalog.json",
                exe_dir / "data" / "default_tools_catalog.json",
            ]
        )
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            bundle_path = Path(bundle_dir)
            candidates.extend(
                [
                    bundle_path / relative,
                    bundle_path / "default_tools_catalog.json",
                    bundle_path / "data" / "default_tools_catalog.json",
                ]
            )
    return candidates
