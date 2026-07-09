"""Тесты resolver-а установленных браузеров."""

from __future__ import annotations

from agent_desktop_constructor.workers import browser_detect


def test_normalize_browser_id_supports_yandex_aliases() -> None:
    """Русские и английские названия Яндекс Браузера дают id=yandex."""
    assert browser_detect.normalize_browser_id("яндекс") == "yandex"
    assert browser_detect.normalize_browser_id("Яндекс Браузер") == "yandex"
    assert browser_detect.normalize_browser_id("Yandex Browser") == "yandex"


def test_resolve_browser_executable_uses_alias(monkeypatch) -> None:
    """resolve_browser_executable ищет executable по нормализованному id."""

    def fake_find_browser_executable(known_browser):
        if known_browser.name == "yandex":
            return "C:/Yandex/browser.exe"
        return None

    monkeypatch.setattr(
        browser_detect,
        "_find_browser_executable",
        fake_find_browser_executable,
    )

    assert browser_detect.resolve_browser_executable("яндекс") == "C:/Yandex/browser.exe"
    assert browser_detect.resolve_browser_executable("yandex") == "C:/Yandex/browser.exe"


def test_yandex_default_user_data_dir_uses_localappdata(monkeypatch) -> None:
    """Штатный профиль Yandex Browser находится в LOCALAPPDATA/User Data."""
    monkeypatch.setattr(browser_detect.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/me/AppData/Local")

    expected = r"C:\Users\me\AppData\Local\Yandex\YandexBrowser\User Data"

    assert browser_detect.resolve_default_user_data_dir("yandex") == expected
    assert browser_detect.resolve_default_user_data_dir("яндекс") == expected


def test_list_installed_browsers_contains_id_and_path(monkeypatch) -> None:
    """Список браузеров отдаёт стабильный id/name/path для выбора tool-ом."""

    def fake_find_browser_executable(known_browser):
        if known_browser.name == "yandex":
            return "C:/Yandex/browser.exe"
        return None

    monkeypatch.setattr(
        browser_detect,
        "_find_browser_executable",
        fake_find_browser_executable,
    )
    monkeypatch.setattr(
        browser_detect,
        "_detect_chromium_version",
        lambda path: "25.1.0.0",
    )

    browsers = browser_detect.list_installed_browsers()

    assert browsers == [
        {
            "id": "yandex",
            "name": "yandex",
            "family": "chromium",
            "path": "C:/Yandex/browser.exe",
            "executable_path": "C:/Yandex/browser.exe",
            "version": "25.1.0.0",
            "supports_cdp": True,
            "readable": True,
        }
    ]


def test_find_readable_browser_uses_alias() -> None:
    """find_readable_browser принимает русское имя браузера."""
    browser = browser_detect.find_readable_browser("яндекс")

    assert browser is not None
    assert browser.name == "yandex"
def test_list_installed_browsers_detects_via_which(monkeypatch) -> None:
    """Найденный по PATH браузер попадает в список с корректными полями."""

    def fake_which(command: str):
        return "/usr/bin/google-chrome" if command in {"chrome", "google-chrome"} else None

    monkeypatch.setattr(browser_detect.shutil, "which", fake_which)

    browsers = browser_detect.list_installed_browsers()

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

    assert browser_detect.resolve_browser_executable("edge") == "/usr/bin/msedge"
    assert browser_detect.resolve_browser_executable("эдж") == "/usr/bin/msedge"
    assert browser_detect.resolve_browser_executable("unknown-browser") is None


def test_find_readable_browser_only_chromium() -> None:
    """Chromium читается через CDP, Firefox — нет."""
    assert browser_detect.find_readable_browser("edge") is not None
    assert browser_detect.find_readable_browser("chrome") is not None
    assert browser_detect.find_readable_browser("firefox") is None
    assert browser_detect.find_readable_browser("unknown") is None
