"""Локальное JSON-хранилище настроек desktop UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from agent_desktop_constructor.app.core.config import (
    AppConfig,
    FIXED_LLM_MODEL_NAME,
    runtime_base_dir,
)

DEFAULT_SETTINGS_PATH = str(runtime_base_dir() / "data" / "settings.json")


def _bundled_settings_path() -> Path | None:
    """Вернуть readonly settings из PyInstaller bundle, если он существует."""
    if not getattr(sys, "frozen", False):
        return None
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        return None
    candidate = Path(bundle_dir) / "data" / "settings.json"
    return candidate if candidate.exists() else None


def load_settings(path: str | None = None) -> AppConfig:
    """Загрузить AppConfig из settings.json или вернуть AppConfig() по умолчанию.

    В frozen exe настройки могут быть split на две части:
    - bundled readonly ``_internal/data/settings.json`` с базовыми параметрами
      (например llm_proxy_url);
    - пользовательский ``data/settings.json`` рядом с exe, куда UI сохраняет
      выбранную модель.

    Поэтому при обычной загрузке exe мы мержим bundled base + user overrides.
    Иначе частичный файл вида ``{"llm_model_name": "..."}`` потеряет proxy URL.
    """
    settings_path = Path(path or DEFAULT_SETTINGS_PATH)
    payload: dict = {}
    if path is None:
        bundled = _bundled_settings_path()
        if bundled is not None:
            payload.update(_read_settings_payload(bundled))
    if settings_path.exists():
        payload.update(_read_settings_payload(settings_path))
    if not payload:
        return AppConfig()

    # LLM в приложении всегда фиксирована — игнорируем старые значения из UI.
    payload["llm_model_name"] = FIXED_LLM_MODEL_NAME

    try:
        return AppConfig.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Некорректные настройки приложения: {exc}") from exc


def _read_settings_payload(settings_path: Path) -> dict:
    """Прочитать JSON settings и вернуть объект настроек."""
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON настроек: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Файл настроек должен содержать JSON-объект")
    return payload


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


def save_llm_model_name(model_name: str, path: str | None = None) -> None:
    """Сохранить фиксированную LLM в settings.json (выбор пользователя отключён)."""
    del model_name  # аргумент оставлен для совместимости вызовов
    settings_path = Path(path or DEFAULT_SETTINGS_PATH)
    if settings_path.exists():
        payload = _read_settings_payload(settings_path)
    elif path is None and (bundled := _bundled_settings_path()) is not None:
        payload = _read_settings_payload(bundled)
    else:
        payload = {}

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload["llm_model_name"] = FIXED_LLM_MODEL_NAME
    settings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

