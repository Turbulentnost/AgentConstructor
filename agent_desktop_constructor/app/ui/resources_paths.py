"""Пути к UI-ресурсам (логотип, иконки навигации)."""

from __future__ import annotations

from pathlib import Path

_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
_ICONS_DIR = _RESOURCES_DIR / "icons"

# SVG-fallback для пунктов меню, если PNG в icons/nav/ отсутствуют.
NAV_SVG_ICONS: dict[str, tuple[str, str]] = {
    "home": ("agents_default.svg", "agents_active.svg"),
    "agents": ("agents_default.svg", "agents_active.svg"),
    "constructor": ("create_default.svg", "create_active.svg"),
    "tasks": ("journal_default.svg", "journal_active.svg"),
    "analytics": ("analytics_default.svg", "analytics_active.svg"),
    "settings": ("settings_default.svg", "settings_active.svg"),
}

BRAND_LOGO_SVG_FALLBACK = "create_active.svg"


def resources_dir() -> Path:
    """Корневая папка ``app/ui/resources``."""
    return _RESOURCES_DIR


def brand_logo_path() -> Path:
    """PNG логотипа приложения."""
    return _RESOURCES_DIR / "brand" / "logo.png"


def brand_logo_svg_fallback_path() -> Path:
    """SVG-заглушка логотипа, если PNG ещё не добавлен."""
    return _ICONS_DIR / BRAND_LOGO_SVG_FALLBACK


def nav_icon_path(name: str) -> Path:
    """PNG иконки пункта навигации (``home``, ``agents``, …)."""
    return _RESOURCES_DIR / "icons" / "nav" / f"{name}.png"


def nav_icon_svg_path(name: str, *, active: bool = False) -> Path | None:
    """SVG иконки пункта навигации для fallback."""
    files = NAV_SVG_ICONS.get(name)
    if files is None:
        return None
    return _ICONS_DIR / files[1 if active else 0]
