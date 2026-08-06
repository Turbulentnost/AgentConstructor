"""Тесты JSON-настроек AppConfig."""

import json
import sys
from pathlib import Path

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig, runtime_base_dir
from agent_desktop_constructor.app.core.settings import (
    load_settings,
    save_llm_model_name,
    save_settings,
)


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


def test_save_llm_model_name_updates_only_model_name(tmp_path: Path) -> None:
    """save_llm_model_name не перезаписывает остальные ключи settings."""
    path = tmp_path / "settings.json"
    path.write_text(
        '{"run_mode":"offline","custom_key":{"enabled":true}}',
        encoding="utf-8",
    )

    from agent_desktop_constructor.app.core.config import FIXED_LLM_MODEL_NAME

    save_llm_model_name("chatgpt:reason", str(path))

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "run_mode": "offline",
        "custom_key": {"enabled": True},
        "llm_model_name": FIXED_LLM_MODEL_NAME,
    }


def test_save_llm_model_name_creates_minimal_settings(tmp_path: Path) -> None:
    """save_llm_model_name создаёт минимальный settings.json с фиксированной LLM."""
    from agent_desktop_constructor.app.core.config import FIXED_LLM_MODEL_NAME

    path = tmp_path / "nested" / "settings.json"

    save_llm_model_name("lmstudio", str(path))

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "llm_model_name": FIXED_LLM_MODEL_NAME
    }


def test_broken_json_raises_clear_error(tmp_path: Path) -> None:
    """Битый JSON даёт понятную ошибку."""
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Некорректный JSON настроек"):
        load_settings(str(path))


def test_settings_json_with_utf8_bom_is_accepted(tmp_path: Path) -> None:
    """Windows tools могут добавить UTF-8 BOM — settings всё равно читаются."""
    path = tmp_path / "settings.json"
    path.write_text('{"run_mode":"offline"}', encoding="utf-8-sig")

    config = load_settings(str(path))

    assert config.run_mode == AppRunMode.OFFLINE


def test_frozen_runtime_paths_are_next_to_exe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В exe data/agents.db и agent_workspaces создаются рядом с exe."""
    exe_path = tmp_path / "AgentConstructor.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))

    config = AppConfig(database_path="./data/agents.db")

    assert runtime_base_dir() == tmp_path
    assert config.resolve_database_path() == tmp_path / "data" / "agents.db"
    assert config.resolve_agent_workspaces_root() == tmp_path / "data" / "agent_workspaces"


def test_frozen_settings_loads_bundled_default_when_user_settings_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Первый запуск exe может прочитать readonly settings из bundle."""
    user_dir = tmp_path / "dist"
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "data").mkdir(parents=True)
    (bundle_dir / "data" / "settings.json").write_text(
        '{"run_mode":"offline"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(user_dir / "AgentConstructor.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(
        "agent_desktop_constructor.app.core.settings.DEFAULT_SETTINGS_PATH",
        str(user_dir / "data" / "settings.json"),
    )

    config = load_settings()

    assert config.run_mode == AppRunMode.OFFLINE


def test_frozen_settings_merges_user_overrides_with_bundled_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Частичный user settings не должен затирать llm_proxy_url из bundle."""
    user_dir = tmp_path / "dist"
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "data").mkdir(parents=True)
    (user_dir / "data").mkdir(parents=True)
    (bundle_dir / "data" / "settings.json").write_text(
        json.dumps(
            {
                "run_mode": "outlook_readonly",
                "agent_build_mode": "llm_agent_loop",
                "llm_model_name": "chatgpt:internal",
                "llm_proxy_url": "http://192.168.2.135:8080",
                "use_llm_planner": True,
            }
        ),
        encoding="utf-8",
    )
    (user_dir / "data" / "settings.json").write_text(
        '{"llm_model_name":"claude-opus-4.6:internal"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(user_dir / "AgentConstructor.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(
        "agent_desktop_constructor.app.core.settings.DEFAULT_SETTINGS_PATH",
        str(user_dir / "data" / "settings.json"),
    )

    config = load_settings()

    from agent_desktop_constructor.app.core.config import FIXED_LLM_MODEL_NAME

    assert config.llm_proxy_url == "http://192.168.2.135:8080"
    assert config.llm_model_name == FIXED_LLM_MODEL_NAME
    assert config.run_mode == AppRunMode.OUTLOOK_READONLY


def test_save_llm_model_name_preserves_bundled_proxy_when_user_settings_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сохранение выбранной модели создаёт full settings с proxy из bundle."""
    user_dir = tmp_path / "dist"
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "data").mkdir(parents=True)
    (bundle_dir / "data" / "settings.json").write_text(
        json.dumps(
            {
                "llm_proxy_url": "http://192.168.2.135:8080",
                "llm_model_name": "chatgpt:internal",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(user_dir / "AgentConstructor.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    settings_path = user_dir / "data" / "settings.json"
    monkeypatch.setattr(
        "agent_desktop_constructor.app.core.settings.DEFAULT_SETTINGS_PATH",
        str(settings_path),
    )

    from agent_desktop_constructor.app.core.config import FIXED_LLM_MODEL_NAME

    save_llm_model_name("lmstudio")

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["llm_proxy_url"] == "http://192.168.2.135:8080"
    assert payload["llm_model_name"] == FIXED_LLM_MODEL_NAME

