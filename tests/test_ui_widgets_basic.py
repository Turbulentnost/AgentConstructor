"""Базовые behavior-тесты UI widgets."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_desktop_constructor.app.core.models.human_approval import HumanApprovalRecord
from agent_desktop_constructor.app.core.models.run_events import (
    AgentRunEvent,
    AgentRunEventType,
)
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from tests.test_storage import make_agent_spec

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    """Создать QApplication для headless UI-тестов."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeUiService:
    """Service-заглушка для проверки UI boundaries."""

    def __init__(self) -> None:
        """Создать fake service."""
        self.agent_spec = make_agent_spec()
        self.state = AgentRuntimeState(
            run_id="run-1",
            agent_id=self.agent_spec.agent_id,
            status=AgentRunStatus.COMPLETED,
            errors=["SEND_DISABLED_FOR_SAFETY"],
        )
        self.approval = HumanApprovalRecord(
            approval_id="approval-1",
            run_id="run-1",
            agent_id=self.agent_spec.agent_id,
            node_id="review",
            tool_name="email.send",
            question="Отправить письмо?",
            options=["Подтвердить", "Отклонить"],
        )
        self.calls: list[str] = []

    def list_agents(self):
        """Вернуть агентов."""
        self.calls.append("list_agents")
        return [self.agent_spec]

    def build_preview(self, user_request: str):
        """Вернуть preview."""
        self.calls.append(f"build_preview:{user_request}")
        return self.agent_spec

    def save_agent(self, agent_spec) -> None:
        """Сохранить агента."""
        self.calls.append(f"save_agent:{agent_spec.agent_id}")

    def create_agent_from_request(self, user_request: str, save: bool = True):
        """Создать и сохранить агента."""
        self.calls.append(f"create_agent_from_request:{user_request}:{save}")
        return self.agent_spec

    def run_agent(self, agent_id: str):
        """Запустить агента."""
        self.calls.append(f"run_agent:{agent_id}")
        return self.state

    def list_runs(self, agent_id: str):
        """Вернуть запуски."""
        self.calls.append(f"list_runs:{agent_id}")
        return [self.state]

    def list_run_events(self, run_id: str):
        """Вернуть события."""
        self.calls.append(f"list_run_events:{run_id}")
        return [
            AgentRunEvent(
                event_id="event-1",
                run_id=run_id,
                event_type=AgentRunEventType.RUN_STARTED,
                message="Старт",
                details={"ключ": "значение"},
            )
        ]

    def list_pending_approvals(self):
        """Вернуть pending approvals."""
        self.calls.append("list_pending_approvals")
        return [self.approval]

    def resume_run_by_approval(
        self,
        approval_id: str,
        approved: bool,
        comment: str | None = None,
    ):
        """Продолжить запуск по approval."""
        self.calls.append(f"resume_run_by_approval:{approval_id}:{approved}:{comment}")
        return self.state


class FakeUiContainer:
    """Минимальный fake container."""

    def __init__(self) -> None:
        """Создать container."""
        self.agent_service = FakeUiService()


def test_all_widgets_can_be_created(qt_app) -> None:
    """Все ключевые widgets создаются."""
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )
    from agent_desktop_constructor.app.ui.widgets.agent_list_widget import AgentListWidget
    from agent_desktop_constructor.app.ui.widgets.approval_queue_widget import (
        ApprovalQueueWidget,
    )
    from agent_desktop_constructor.app.ui.widgets.run_events_widget import RunEventsWidget
    from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget

    container = FakeUiContainer()

    assert AgentListWidget(container) is not None
    assert AgentCreateWidget(container) is not None
    assert RunListWidget(container) is not None
    assert RunEventsWidget(container) is not None
    assert ApprovalQueueWidget(container) is not None


def test_agent_selection_does_not_run_agent(qt_app) -> None:
    """Выбор агента в AgentListWidget не запускает агента."""
    from agent_desktop_constructor.app.ui.widgets.agent_list_widget import AgentListWidget

    container = FakeUiContainer()
    widget = AgentListWidget(container)
    widget.refresh()
    widget.table.selectRow(0)

    assert container.agent_service.calls == ["list_agents"]
    assert "run_agent:agent-1" not in container.agent_service.calls


def test_preview_and_save_use_service(qt_app, monkeypatch) -> None:
    """Preview вызывает build_preview, save вызывает save_agent."""
    from agent_desktop_constructor.app.ui.widgets import agent_create_widget
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    monkeypatch.setattr(agent_create_widget, "show_info", lambda *args, **kwargs: None)
    container = FakeUiContainer()
    widget = AgentCreateWidget(container)
    widget.request_edit.setPlainText("создай агента")

    widget.build_preview()
    widget.save_agent()

    assert container.agent_service.calls == [
        "build_preview:создай агента",
        "save_agent:agent-1",
    ]
    assert widget.tabs.count() == 5
    assert widget.tools_table.rowCount() == len(container.agent_service.agent_spec.tools)


def test_save_without_preview_uses_create_agent_from_request(qt_app, monkeypatch) -> None:
    """Save без preview вызывает create_agent_from_request."""
    from agent_desktop_constructor.app.ui.widgets import agent_create_widget
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    monkeypatch.setattr(agent_create_widget, "show_info", lambda *args, **kwargs: None)
    container = FakeUiContainer()
    widget = AgentCreateWidget(container)
    widget.request_edit.setPlainText("новый агент")

    widget.save_agent()

    assert container.agent_service.calls == [
        "create_agent_from_request:новый агент:True"
    ]


def test_approval_refresh_and_approve_use_service(qt_app, monkeypatch) -> None:
    """ApprovalQueueWidget читает очередь и approve вызывает resume_run_by_approval."""
    from agent_desktop_constructor.app.ui.widgets import approval_queue_widget
    from agent_desktop_constructor.app.ui.widgets.approval_queue_widget import (
        ApprovalQueueWidget,
    )

    messages: list[str] = []
    monkeypatch.setattr(
        approval_queue_widget,
        "show_info",
        lambda _parent, _title, message: messages.append(message),
    )
    container = FakeUiContainer()
    widget = ApprovalQueueWidget(container)

    widget.refresh()
    widget.table.selectRow(0)
    widget.approve_selected()

    assert container.agent_service.calls == [
        "list_pending_approvals",
        "resume_run_by_approval:approval-1:True:None",
        "list_pending_approvals",
    ]
    assert any("отправка писем заблокирована" in message for message in messages)


def test_auto_refresh_timers_can_be_toggled(qt_app) -> None:
    """Auto-refresh timers можно включить и выключить."""
    from agent_desktop_constructor.app.ui.widgets.approval_queue_widget import (
        ApprovalQueueWidget,
    )
    from agent_desktop_constructor.app.ui.widgets.run_events_widget import RunEventsWidget
    from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget

    container = FakeUiContainer()
    widgets = [
        RunListWidget(container),
        RunEventsWidget(container),
        ApprovalQueueWidget(container),
    ]

    for widget in widgets:
        widget.auto_refresh_checkbox.setChecked(True)
        assert widget._timer.isActive()
        widget.auto_refresh_checkbox.setChecked(False)
        assert not widget._timer.isActive()


@pytest.mark.parametrize("forbidden", ["pywin32", "pythoncom", "win32com"])
def test_ui_source_does_not_import_com_modules(forbidden: str) -> None:
    """UI не импортирует pywin32/pythoncom/win32com напрямую."""
    ui_dir = Path("agent_desktop_constructor/app/ui")
    source = "\n".join(path.read_text(encoding="utf-8") for path in ui_dir.rglob("*.py"))

    assert forbidden not in source

