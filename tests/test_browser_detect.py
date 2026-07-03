"""Тесты определения установленных браузеров."""

from __future__ import annotations

from agent_desktop_constructor.workers import browser_detect
from agent_desktop_constructor.workers.browser_detect import (
    find_readable_browser,
    list_installed_browsers,
    resolve_browser_executable,
)


def test_list_installed_browsers_detects_via_which(monkeypatch) -> None:
    """Найденный по PATH браузер попадает в список с корректными полями."""

    def fake_which(command: str):
        return "/usr/bin/google-chrome" if command in {"chrome", "google-chrome"} else None

    monkeypatch.setattr(browser_detect.shutil, "which", fake_which)

    browsers = list_installed_browsers()

    chrome = next((item for item in browsers if item["name"] == "chrome"), None)
    assert chrome is not None
    assert chrome["family"] == "chromium"
    assert chrome["supports_cdp"] is True
    assert chrome["executable_path"] == "/usr/bin/google-chrome"


def test_resolve_browser_executable_supports_aliases(monkeypatch) -> None:
    """Дружественные имена и русские алиасы резолвятся в исполняемый файл."""

    def fake_which(command: str):
        return "/usr/bin/msedge" if command == "msedge" else None

    monkeypatch.setattr(browser_detect.shutil, "which", fake_which)

    assert resolve_browser_executable("edge") == "/usr/bin/msedge"
    assert resolve_browser_executable("эдж") == "/usr/bin/msedge"
    assert resolve_browser_executable("unknown-browser") is None


def test_find_readable_browser_only_chromium() -> None:
    """Chromium читается через CDP, Firefox — нет."""
    assert find_readable_browser("edge") is not None
    assert find_readable_browser("chrome") is not None
    assert find_readable_browser("firefox") is None
    assert find_readable_browser("unknown") is None
