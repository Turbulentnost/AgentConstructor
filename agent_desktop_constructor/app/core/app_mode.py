"""Режимы запуска приложения."""

from enum import StrEnum


class AppRunMode(StrEnum):
    """Режим сборки инструментов и внешних интеграций приложения."""

    FAKE = "fake"
    OUTLOOK_READONLY = "outlook_readonly"
    OFFLINE = "offline"

