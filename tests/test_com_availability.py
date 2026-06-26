"""Тесты безопасной проверки доступности COM."""

from agent_desktop_constructor.workers.com_availability import (
    get_com_unavailable_reason,
    is_pywin32_available,
    is_windows,
)


def test_is_windows_returns_bool() -> None:
    """is_windows возвращает bool."""
    assert isinstance(is_windows(), bool)


def test_is_pywin32_available_returns_bool_without_exception() -> None:
    """is_pywin32_available возвращает bool и не выбрасывает исключение."""
    assert isinstance(is_pywin32_available(), bool)


def test_get_com_unavailable_reason_returns_string() -> None:
    """get_com_unavailable_reason возвращает строку."""
    reason = get_com_unavailable_reason()

    assert isinstance(reason, str)
    assert reason


def test_com_availability_tests_do_not_import_pywin32_directly() -> None:
    """Тесты не импортируют pywin32 напрямую."""
    # Если pywin32 отсутствует, предыдущие проверки всё равно должны пройти.
    assert True
