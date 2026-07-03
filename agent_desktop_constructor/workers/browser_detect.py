"""Определение установленных на устройстве браузеров (read-only, без запуска).

Модуль ищет исполняемые файлы известных браузеров по PATH и типовым путям
Windows/macOS/Linux и определяет версию, не запуская браузер. Chromium-семейство
(Edge/Chrome/Brave/Yandex/Opera/Vivaldi/Chromium) поддерживает управление через
Chrome DevTools Protocol, поэтому для него доступно чтение страниц. Firefox
использует другой протокол и помечается как не поддерживающий CDP-чтение.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_VERSION_DIR_RE = re.compile(r"^\d+\.\d+[\d.]*$")


@dataclass(frozen=True)
class KnownBrowser:
    """Описание известного браузера для поиска на устройстве."""

    name: str
    family: str
    which_commands: tuple[str, ...]
    windows_relative_paths: tuple[str, ...]
    posix_paths: tuple[str, ...]

    @property
    def supports_cdp(self) -> bool:
        """CDP-чтение доступно только для Chromium-семейства."""
        return self.family == "chromium"


KNOWN_BROWSERS: tuple[KnownBrowser, ...] = (
    KnownBrowser(
        name="edge",
        family="chromium",
        which_commands=("msedge",),
        windows_relative_paths=("Microsoft/Edge/Application/msedge.exe",),
        posix_paths=(
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ),
    ),
    KnownBrowser(
        name="chrome",
        family="chromium",
        which_commands=("chrome", "google-chrome", "google-chrome-stable"),
        windows_relative_paths=("Google/Chrome/Application/chrome.exe",),
        posix_paths=(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ),
    ),
    KnownBrowser(
        name="brave",
        family="chromium",
        which_commands=("brave", "brave-browser"),
        windows_relative_paths=(
            "BraveSoftware/Brave-Browser/Application/brave.exe",
        ),
        posix_paths=(
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ),
    ),
    KnownBrowser(
        name="yandex",
        family="chromium",
        which_commands=("yandex", "yandex-browser"),
        windows_relative_paths=("Yandex/YandexBrowser/Application/browser.exe",),
        posix_paths=(
            "/Applications/Yandex.app/Contents/MacOS/Yandex",
        ),
    ),
    KnownBrowser(
        name="opera",
        family="chromium",
        which_commands=("opera",),
        windows_relative_paths=(
            "Opera/opera.exe",
            "Programs/Opera/opera.exe",
        ),
        posix_paths=("/Applications/Opera.app/Contents/MacOS/Opera",),
    ),
    KnownBrowser(
        name="vivaldi",
        family="chromium",
        which_commands=("vivaldi",),
        windows_relative_paths=("Vivaldi/Application/vivaldi.exe",),
        posix_paths=("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",),
    ),
    KnownBrowser(
        name="chromium",
        family="chromium",
        which_commands=("chromium", "chromium-browser"),
        windows_relative_paths=("Chromium/Application/chrome.exe",),
        posix_paths=("/Applications/Chromium.app/Contents/MacOS/Chromium",),
    ),
    KnownBrowser(
        name="firefox",
        family="gecko",
        which_commands=("firefox",),
        windows_relative_paths=("Mozilla Firefox/firefox.exe",),
        posix_paths=("/Applications/Firefox.app/Contents/MacOS/firefox",),
    ),
)


def _windows_base_dirs() -> list[Path]:
    """Типовые базовые директории установки браузеров на Windows."""
    env_vars = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "APPDATA")
    dirs: list[Path] = []
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            dirs.append(Path(value))
    return dirs


def _find_browser_executable(browser: KnownBrowser) -> str | None:
    """Найти путь к исполняемому файлу браузера, ничего не запуская."""
    for command in browser.which_commands:
        found = shutil.which(command)
        if found:
            return found
    if os.name == "nt":
        for base_dir in _windows_base_dirs():
            for relative in browser.windows_relative_paths:
                candidate = base_dir / relative
                if candidate.exists():
                    return str(candidate)
    for posix_path in browser.posix_paths:
        candidate = Path(posix_path)
        if candidate.exists():
            return str(candidate)
    return None


def _detect_chromium_version(executable_path: str) -> str | None:
    """Определить версию Chromium по версионной подпапке рядом с exe."""
    application_dir = Path(executable_path).parent
    versions: list[tuple[int, ...]] = []
    try:
        entries = list(application_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.is_dir() and _VERSION_DIR_RE.match(entry.name):
            parts = tuple(int(part) for part in entry.name.split(".") if part.isdigit())
            if parts:
                versions.append(parts)
    if not versions:
        return None
    best = max(versions)
    return ".".join(str(part) for part in best)


def list_installed_browsers() -> list[dict]:
    """Вернуть список установленных браузеров с путями, версией и CDP-поддержкой."""
    browsers: list[dict] = []
    for browser in KNOWN_BROWSERS:
        executable_path = _find_browser_executable(browser)
        if executable_path is None:
            continue
        version = (
            _detect_chromium_version(executable_path)
            if browser.family == "chromium"
            else None
        )
        browsers.append(
            {
                "name": browser.name,
                "family": browser.family,
                "executable_path": executable_path,
                "version": version,
                "supports_cdp": browser.supports_cdp,
                "readable": browser.supports_cdp,
            }
        )
    return browsers


def resolve_browser_executable(name: str) -> str | None:
    """Найти исполняемый файл браузера по дружественному имени (edge/chrome/...)."""
    normalized = (name or "").strip().casefold()
    if not normalized:
        return None
    aliases = {
        "microsoft edge": "edge",
        "google chrome": "chrome",
        "brave browser": "brave",
        "yandex browser": "yandex",
        "яндекс": "yandex",
        "яндекс браузер": "yandex",
        "хром": "chrome",
        "гугл хром": "chrome",
        "эдж": "edge",
    }
    normalized = aliases.get(normalized, normalized)
    for browser in KNOWN_BROWSERS:
        if browser.name == normalized:
            return _find_browser_executable(browser)
    return None


def find_readable_browser(name: str) -> KnownBrowser | None:
    """Найти известный CDP-совместимый браузер по имени."""
    normalized = (name or "").strip().casefold()
    for browser in KNOWN_BROWSERS:
        if browser.name == normalized and browser.supports_cdp:
            return browser
    return None
