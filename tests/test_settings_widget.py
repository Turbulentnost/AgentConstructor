"""Тесты SettingsWidget."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from agent_desktop_constructor.app.ui.widgets.settings_widget import (  # noqa: E402
    SettingsWidget,
)


@pytest.fixture(scope="session")
def qt_app():
    """Создать QApplication."""
    return QApplication.instance() or QApplication([])


def test_settings_widget_can_be_created(qt_app, tmp_path: Path) -> None:
    """SettingsWidget создаётся."""
    widget = SettingsWidget(settings_path=str(tmp_path / "settings.json"))

    assert widget.run_mode_combo.count() == 3


def test_fields_are_filled_from_app_config(qt_app, tmp_path: Path) -> None:
    """Поля заполняются из AppConfig."""
    widget = SettingsWidget(settings_path=str(tmp_path / "settings.json"))
    config = AppConfig(
        run_mode=AppRunMode.OFFLINE,
        database_path="./data/custom.db",
        use_llm_planner=True,
        com_worker_timeout_seconds=33,
    )

    widget.set_config(config)

    assert widget.run_mode_combo.currentData() == "offline"
    assert widget.database_path_edit.text() == "./data/custom.db"
    assert widget.use_llm_planner_checkbox.isChecked() is True
    assert widget.com_worker_timeout_spin.value() == 33


def test_config_is_collected_from_fields(qt_app, tmp_path: Path) -> None:
    """Из полей собирается AppConfig."""
    widget = SettingsWidget(settings_path=str(tmp_path / "settings.json"))
    widget.run_mode_combo.setCurrentIndex(widget.run_mode_combo.findData("outlook_readonly"))
    widget.database_path_edit.setText("./data/ui.db")
    widget.use_llm_planner_checkbox.setChecked(False)
    widget.llm_base_url_edit.setText("http://localhost:1234")
    widget.llm_model_name_edit.setText("local-model")
    widget.com_safe_mode_checkbox.setChecked(True)
    widget.com_worker_timeout_spin.setValue(44)

    config = widget.config_from_fields()

    assert config.run_mode == AppRunMode.OUTLOOK_READONLY
    assert config.database_path == "./data/ui.db"
    assert config.com_worker_timeout_seconds == 44


def test_validate_settings_does_not_call_com_or_llm(
    qt_app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Проверка настроек не вызывает COM и LLM."""
    from agent_desktop_constructor.app.ui.widgets import settings_widget

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Не должно вызываться при локальной проверке")

    monkeypatch.setattr(settings_widget, "show_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(settings_widget, "show_error", fail_if_called)
    widget = SettingsWidget(settings_path=str(tmp_path / "settings.json"))

    widget.validate_settings()


def test_reset_defaults_works(qt_app, tmp_path: Path) -> None:
    """Сброс по умолчанию заполняет AppConfig()."""
    widget = SettingsWidget(settings_path=str(tmp_path / "settings.json"))
    widget.database_path_edit.setText("./custom.db")

    widget.reset_defaults()

    assert widget.config_from_fields() == AppConfig()


def test_ui_source_does_not_import_pywin32(qt_app) -> None:
    """Settings UI не импортирует pywin32 напрямую."""
    source = Path(
        "agent_desktop_constructor/app/ui/widgets/settings_widget.py"
    ).read_text(encoding="utf-8")

    assert "pywin32" not in source
    assert "pythoncom" not in source
    assert "win32com" not in source

