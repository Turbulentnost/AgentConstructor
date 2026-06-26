"""Тесты JSON-настроек AppConfig."""

from pathlib import Path

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.settings import load_settings, save_settings


def test_load_settings_returns_default_when_file_missing(tmp_path: Path) -> None:
    """Если файла нет, load_settings возвращает AppConfig()."""
    config = load_settings(str(tmp_path / "missing.json"))

    assert config == AppConfig()


def test_save_settings_creates_json(tmp_path: Path) -> None:
    """save_settings создаёт JSON файл."""
    path = tmp_path / "settings.json"

    save_settings(AppConfig(run_mode=AppRunMode.OFFLINE), str(path))

    assert path.exists()
    assert "offline" in path.read_text(encoding="utf-8")


def test_load_settings_restores_app_config(tmp_path: Path) -> None:
    """load_settings восстанавливает AppConfig."""
    path = tmp_path / "settings.json"
    original = AppConfig(
        run_mode=AppRunMode.OUTLOOK_READONLY,
        database_path="./data/тест.db",
        use_llm_planner=True,
    )
    save_settings(original, str(path))

    restored = load_settings(str(path))

    assert restored == original


def test_russian_text_is_preserved(tmp_path: Path) -> None:
    """Русский текст не ломается в JSON."""
    path = tmp_path / "settings.json"
    config = AppConfig(database_path="./data/агенты.db")

    save_settings(config, str(path))

    assert "агенты" in path.read_text(encoding="utf-8")


def test_save_settings_creates_parent_directory(tmp_path: Path) -> None:
    """save_settings создаёт parent directory."""
    path = tmp_path / "nested" / "settings.json"

    save_settings(AppConfig(), str(path))

    assert path.exists()


def test_broken_json_raises_clear_error(tmp_path: Path) -> None:
    """Битый JSON даёт понятную ошибку."""
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Некорректный JSON настроек"):
        load_settings(str(path))

