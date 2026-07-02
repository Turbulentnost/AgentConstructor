"""Локальное JSON-хранилище настроек desktop UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from agent_desktop_constructor.app.core.config import AppConfig

DEFAULT_SETTINGS_PATH = str(
    (Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) if getattr(sys, "frozen", False) else Path("."))
    / "data"
    / "settings.json"
)


def load_settings(path: str | None = None) -> AppConfig:
    """Загрузить AppConfig из settings.json или вернуть AppConfig() по умолчанию."""
    settings_path = Path(path or DEFAULT_SETTINGS_PATH)
    if not settings_path.exists():
        return AppConfig()

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON настроек: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Файл настроек должен содержать JSON-объект")

    try:
        return AppConfig.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Некорректные настройки приложения: {exc}") from exc


def save_settings(config: AppConfig, path: str | None = None) -> None:
    """Сохранить AppConfig в UTF-8 JSON без секретов."""
    settings_path = Path(path or DEFAULT_SETTINGS_PATH)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json")
    payload.pop("llm_api_key", None)
    settings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

