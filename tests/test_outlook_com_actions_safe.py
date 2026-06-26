"""Тесты безопасных Outlook COM actions без реального Outlook."""

import pytest

from agent_desktop_constructor.workers import outlook_com_actions as actions
from agent_desktop_constructor.workers.outlook_com_errors import (
    ComUnavailableError,
    DangerousOutlookActionBlockedError,
    OutlookComError,
)


class BrokenStr:
    """Объект, падающий при приведении к строке."""

    def __str__(self) -> str:
        """Имитировать нестандартный COM-объект."""
        raise RuntimeError("broken str")


def test_matches_query_returns_true_for_empty_query() -> None:
    """Пустой query не фильтрует письмо."""
    assert actions._matches_query("Тема", "Тело", "") is True
    assert actions._matches_query("Тема", "Тело", None) is True


def test_matches_query_finds_term_case_insensitive() -> None:
    """Поиск не учитывает регистр."""
    assert actions._matches_query("Важное Поручение", "", "поручение") is True


def test_matches_query_supports_or() -> None:
    """Query поддерживает простой OR."""
    assert (
        actions._matches_query(
            "Нужно подготовить отчёт",
            "",
            "поручение OR выполнить OR подготовить",
        )
        is True
    )


def test_matches_query_returns_false_when_not_found() -> None:
    """Если ни один термин не найден, возвращается False."""
    assert actions._matches_query("Совещание", "Повестка", "поручение") is False


def test_safe_str_returns_empty_string_for_none_and_broken_value() -> None:
    """_safe_str безопасно обрабатывает None и ошибки str()."""
    assert actions._safe_str(None) == ""
    assert actions._safe_str(BrokenStr()) == ""


def test_send_mail_disabled_always_blocks() -> None:
    """send_mail_disabled всегда блокирует отправку без COM-вызовов."""
    with pytest.raises(DangerousOutlookActionBlockedError):
        actions.send_mail_disabled({})


def test_create_draft_disabled_always_blocks() -> None:
    """create_draft_disabled всегда блокирует создание черновика."""
    with pytest.raises((DangerousOutlookActionBlockedError, OutlookComError)):
        actions.create_draft_disabled({})


def test_load_pywin32_modules_hides_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отсутствие pywin32 превращается в ComUnavailableError, а не ImportError."""
    monkeypatch.setattr(actions.com_availability, "is_windows", lambda: True)

    def raise_import_error(module_name: str):
        raise ImportError(module_name)

    monkeypatch.setattr(actions.importlib, "import_module", raise_import_error)

    with pytest.raises(ComUnavailableError, match="pywin32"):
        actions._load_pywin32_modules()


def test_load_pywin32_modules_hides_unexpected_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Нестандартный сбой загрузки pywin32 тоже превращается в ComUnavailableError."""
    monkeypatch.setattr(actions.com_availability, "is_windows", lambda: True)

    def raise_runtime_error(module_name: str):
        raise RuntimeError(f"{module_name} failed")

    monkeypatch.setattr(actions.importlib, "import_module", raise_runtime_error)

    with pytest.raises(ComUnavailableError, match="pywin32 недоступен"):
        actions._load_pywin32_modules()


def test_search_mail_raises_com_unavailable_without_com(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """search_mail не требует Outlook в unit-тесте и отдаёт ComUnavailableError."""

    def raise_com_unavailable():
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(actions, "_load_pywin32_modules", raise_com_unavailable)

    with pytest.raises(ComUnavailableError, match="COM недоступен"):
        actions.search_mail({})


def test_read_calendar_raises_com_unavailable_without_com(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_calendar не требует Outlook в unit-тесте и отдаёт ComUnavailableError."""

    def raise_com_unavailable():
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(actions, "_load_pywin32_modules", raise_com_unavailable)

    with pytest.raises(ComUnavailableError, match="COM недоступен"):
        actions.read_calendar({})


def test_read_calendar_clamps_limits_without_com(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_calendar сначала нормализует limits, но не импортирует pywin32 в тесте."""

    def raise_com_unavailable():
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(actions, "_load_pywin32_modules", raise_com_unavailable)

    with pytest.raises(ComUnavailableError):
        actions.read_calendar({"days_forward": 999, "max_results": 999})
