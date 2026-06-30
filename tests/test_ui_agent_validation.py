"""Тесты UI-кнопок проверки агента."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from agent_desktop_constructor.app.core.models.agent_validation import (
    AgentValidationResult,
    AgentValidationStatus,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qt_app():
    """Создать QApplication для UI-теста."""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeValidationUiService:
    """Fake service для AgentCreateWidget."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.agent_spec = AgentBuilder().build_from_request("Найди совещания")
        self.validation = AgentValidationResult(
            agent_id=self.agent_spec.agent_id,
            status=AgentValidationStatus.PASSED,
            run_id="run-1",
            errors=[],
            warnings=[],
            summary="ok",
            final_message="Итоговые рекомендации готовы",
            output_data={"recommendations": ["Оставить окно для фокус-работы"]},
            suggested_fixes=[],
        )

    def build_preview(self, user_request: str):
        """Вернуть preview."""
        self.calls.append(f"build_preview:{user_request}")
        return self.agent_spec

    def validate_agent(self, agent_spec, user_request=None):
        """Вернуть validation result."""
        self.calls.append(f"validate_agent:{agent_spec.agent_id}:{user_request}")
        return self.validation

    def create_validate_and_run_once(self, user_request: str):
        """Вернуть validation и runtime state."""
        self.calls.append(f"create_validate_and_run_once:{user_request}")
        return (
            self.agent_spec,
            self.validation,
            AgentRuntimeState(
                run_id="run-main",
                agent_id=self.agent_spec.agent_id,
                status=AgentRunStatus.COMPLETED,
            ),
        )


def test_agent_create_widget_has_validation_buttons(qt_app) -> None:
    """UI имеет кнопки проверки агента."""
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    widget = AgentCreateWidget(SimpleNamespace(agent_service=FakeValidationUiService()))

    assert widget.validate_button.text() == "Проверить агента"
    assert widget.validate_run_button.text() == "Собрать, проверить и запустить"


def test_agent_create_widget_calls_validation_service(qt_app, monkeypatch) -> None:
    """Кнопка проверки вызывает только AgentApplicationService."""
    from agent_desktop_constructor.app.ui import widgets
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    monkeypatch.setattr(widgets.agent_create_widget, "show_info", lambda *args: None)
    service = FakeValidationUiService()
    widget = AgentCreateWidget(SimpleNamespace(agent_service=service))
    widget.request_edit.setPlainText("Найди совещания")

    widget.validate_agent()

    assert service.calls == [
        "build_preview:Найди совещания",
        f"validate_agent:{service.agent_spec.agent_id}:Найди совещания",
    ]
    assert "Итоговый вывод" in widget.general_output.toPlainText()
    assert "Итоговые рекомендации готовы" in widget.general_output.toPlainText()


def test_agent_create_widget_calls_create_validate_and_run(qt_app, monkeypatch) -> None:
    """Кнопка собрать/проверить/запустить вызывает service facade."""
    from agent_desktop_constructor.app.ui import widgets
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    monkeypatch.setattr(widgets.agent_create_widget, "show_info", lambda *args: None)
    service = FakeValidationUiService()
    widget = AgentCreateWidget(SimpleNamespace(agent_service=service))
    widget.request_edit.setPlainText("Найди совещания")

    widget.create_validate_and_run()

    assert service.calls == ["create_validate_and_run_once:Найди совещания"]

