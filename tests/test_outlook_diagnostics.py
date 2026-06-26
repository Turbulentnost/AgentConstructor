"""Тесты Outlook COM diagnostics без Windows/Outlook/pywin32."""

from agent_desktop_constructor.workers import outlook_diagnostics


def test_run_outlook_diagnostics_returns_dict(monkeypatch) -> None:
    """run_outlook_diagnostics возвращает dict."""
    monkeypatch.setattr(outlook_diagnostics.com_availability, "is_windows", lambda: False)

    result = outlook_diagnostics.run_outlook_diagnostics({})

    assert isinstance(result, dict)


def test_diagnostics_contains_steps(monkeypatch) -> None:
    """Результат диагностики содержит steps."""
    monkeypatch.setattr(outlook_diagnostics.com_availability, "is_windows", lambda: False)

    result = outlook_diagnostics.run_outlook_diagnostics({})

    assert "steps" in result["diagnostics"]
    assert result["diagnostics"]["steps"]


def test_diagnostics_returns_structured_error_when_not_windows(monkeypatch) -> None:
    """При недоступном COM диагностика возвращает структурированную ошибку."""
    monkeypatch.setattr(outlook_diagnostics.com_availability, "is_windows", lambda: False)

    result = outlook_diagnostics.run_outlook_diagnostics({})
    first_step = result["diagnostics"]["steps"][0]

    assert result["diagnostics"]["ok"] is False
    assert first_step["step"] == "check_windows"
    assert first_step["ok"] is False
    assert first_step["error_type"] == "RuntimeError"


def test_diagnostics_does_not_raise_import_error(monkeypatch) -> None:
    """ImportError pywin32 превращается в шаг диагностики, а не падает наружу."""
    monkeypatch.setattr(outlook_diagnostics.com_availability, "is_windows", lambda: True)

    def raise_import_error():
        raise ImportError("pythoncom")

    monkeypatch.setattr(
        outlook_diagnostics,
        "_load_pywin32_modules",
        raise_import_error,
    )

    result = outlook_diagnostics.run_outlook_diagnostics({})
    steps = result["diagnostics"]["steps"]

    assert result["diagnostics"]["ok"] is False
    assert steps[-1]["step"] == "load_pywin32"
    assert steps[-1]["error_type"] == "ImportError"


def test_diagnostics_recommendations_are_present(monkeypatch) -> None:
    """При ошибке диагностика возвращает рекомендации."""
    monkeypatch.setattr(outlook_diagnostics.com_availability, "is_windows", lambda: False)

    result = outlook_diagnostics.run_outlook_diagnostics({})

    assert result["diagnostics"]["recommendations"]
