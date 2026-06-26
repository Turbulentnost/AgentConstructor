"""Smoke-тесты PySide6 desktop UI."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig
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

    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def fake_container(tmp_path):
    """Собрать fake container на tmp SQLite без Outlook."""
    return build_application_container(
        AppConfig(
            run_mode=AppRunMode.FAKE,
            database_path=str(tmp_path / "ui-tests.db"),
        )
    )


def test_ui_modules_import() -> None:
    """UI-модули импортируются."""
    pytest.importorskip("PySide6")
    module_names = [
        "agent_desktop_constructor.app.ui.app",
        "agent_desktop_constructor.app.ui.main_window",
        "agent_desktop_constructor.app.ui.widgets.agent_list_widget",
        "agent_desktop_constructor.app.ui.widgets.agent_create_widget",
        "agent_desktop_constructor.app.ui.widgets.run_list_widget",
        "agent_desktop_constructor.app.ui.widgets.run_details_widget",
        "agent_desktop_constructor.app.ui.widgets.run_events_widget",
        "agent_desktop_constructor.app.ui.widgets.approval_queue_widget",
        "agent_desktop_constructor.app.ui.widgets.log_panel_widget",
    ]

    for module_name in module_names:
        assert importlib.import_module(module_name) is not None


def test_main_window_can_be_created(qt_app, fake_container) -> None:
    """MainWindow можно создать с fake ApplicationContainer."""
    from agent_desktop_constructor.app.ui.main_window import MainWindow

    window = MainWindow(fake_container)

    assert window.windowTitle() == "Конструктор ИИ-агентов"
    assert window.pages.count() >= 6


def test_agent_create_widget_can_be_created(qt_app, fake_container) -> None:
    """AgentCreateWidget можно создать."""
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    widget = AgentCreateWidget(fake_container)

    assert widget.request_edit is not None


def test_agent_list_widget_can_be_created(qt_app, fake_container) -> None:
    """AgentListWidget можно создать."""
    from agent_desktop_constructor.app.ui.widgets.agent_list_widget import (
        AgentListWidget,
    )

    widget = AgentListWidget(fake_container)

    assert widget.table.columnCount() == 6


def test_approval_queue_widget_can_be_created(qt_app, fake_container) -> None:
    """ApprovalQueueWidget можно создать."""
    from agent_desktop_constructor.app.ui.widgets.approval_queue_widget import (
        ApprovalQueueWidget,
    )

    widget = ApprovalQueueWidget(fake_container)

    assert widget.table.columnCount() == 7


@pytest.mark.parametrize("forbidden", ["pywin32", "pythoncom", "win32com"])
def test_ui_source_does_not_import_pywin32_modules(forbidden: str) -> None:
    """UI не импортирует pywin32/pythoncom/win32com напрямую."""
    ui_dir = Path("agent_desktop_constructor/app/ui")
    source = "\n".join(path.read_text(encoding="utf-8") for path in ui_dir.rglob("*.py"))

    assert forbidden not in source


def test_window_creation_does_not_call_com(qt_app, monkeypatch, tmp_path) -> None:
    """UI не вызывает COM при создании окна даже в outlook_readonly config."""
    from agent_desktop_constructor.app.ui.main_window import MainWindow
    from agent_desktop_constructor.workers.subprocess_com_worker import (
        SubprocessComWorker,
    )

    def fail_execute(*args, **kwargs):
        raise AssertionError("COM worker не должен выполняться при создании окна")

    monkeypatch.setattr(SubprocessComWorker, "execute", fail_execute)
    container = build_application_container(
        AppConfig(
            run_mode=AppRunMode.OUTLOOK_READONLY,
            database_path=str(tmp_path / "ui-outlook.db"),
        )
    )

    MainWindow(container)


def test_window_creation_does_not_run_runtime(qt_app, fake_container, monkeypatch) -> None:
    """UI не запускает Runtime при создании окна."""
    from agent_desktop_constructor.app.ui.main_window import MainWindow

    def fail_run(*args, **kwargs):
        raise AssertionError("Runtime не должен запускаться при создании окна")

    monkeypatch.setattr(fake_container.runtime, "run", fail_run)

    MainWindow(fake_container)


class FakeUiService:
    """Service-заглушка для проверки, что UI ходит только в service layer."""

    def __init__(self) -> None:
        """Создать service-заглушку со счётчиками."""
        self.agent_spec = make_agent_spec()
        self.state = AgentRuntimeState(
            run_id="run-1",
            agent_id=self.agent_spec.agent_id,
            status=AgentRunStatus.COMPLETED,
        )
        self.approval = HumanApprovalRecord(
            approval_id="approval-1",
            run_id="run-1",
            agent_id=self.agent_spec.agent_id,
            node_id="review",
            question="Продолжить?",
            options=["Подтвердить", "Отклонить"],
        )
        self.calls: list[str] = []

    def build_preview(self, user_request: str):
        """Зафиксировать preview-вызов."""
        self.calls.append(f"build_preview:{user_request}")
        return self.agent_spec

    def list_agents(self):
        """Зафиксировать list_agents-вызов."""
        self.calls.append("list_agents")
        return [self.agent_spec]

    def list_runs(self, agent_id: str):
        """Зафиксировать list_runs-вызов."""
        self.calls.append(f"list_runs:{agent_id}")
        return [self.state]

    def run_agent(self, agent_id: str):
        """Зафиксировать run_agent-вызов."""
        self.calls.append(f"run_agent:{agent_id}")
        return self.state

    def list_run_events(self, run_id: str):
        """Зафиксировать list_run_events-вызов."""
        self.calls.append(f"list_run_events:{run_id}")
        return [
            AgentRunEvent(
                event_id="event-1",
                run_id=run_id,
                event_type=AgentRunEventType.RUN_STARTED,
                message="Запуск агента начат",
            )
        ]

    def list_pending_approvals(self):
        """Зафиксировать list_pending_approvals-вызов."""
        self.calls.append("list_pending_approvals")
        return [self.approval]

    def resume_run_by_approval(
        self,
        approval_id: str,
        approved: bool,
        comment: str | None = None,
    ):
        """Зафиксировать resume_run_by_approval-вызов."""
        self.calls.append(f"resume_run_by_approval:{approval_id}:{approved}:{comment}")
        return self.state


class FakeUiContainer:
    """Минимальный container для UI behavior tests."""

    def __init__(self) -> None:
        """Создать container с fake service."""
        self.agent_service = FakeUiService()


class FakeSynchronousRunManager:
    """Fake manager для проверки RunListWidget без QThread."""

    def is_running(self) -> bool:
        """Запуск не активен."""
        return False

    def start_agent_by_id(self, agent_id: str, service) -> None:
        """Синхронно делегировать запуск fake service."""
        service.run_agent(agent_id)


def test_agent_create_preview_uses_service_without_running_agent(qt_app) -> None:
    """Страница создания делает preview через service и не запускает агента."""
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    container = FakeUiContainer()
    widget = AgentCreateWidget(container)
    widget.request_edit.setPlainText("создай агента")

    widget.build_preview()

    assert container.agent_service.calls == ["build_preview:создай агента"]


def test_agent_list_refresh_uses_service(qt_app) -> None:
    """Страница агентов читает список через service."""
    from agent_desktop_constructor.app.ui.widgets.agent_list_widget import (
        AgentListWidget,
    )

    container = FakeUiContainer()
    widget = AgentListWidget(container)

    widget.refresh()

    assert container.agent_service.calls == ["list_agents"]
    assert widget.table.rowCount() == 1


def test_run_list_actions_use_service(qt_app, monkeypatch) -> None:
    """Страница запусков читает и запускает агента только через service."""
    from agent_desktop_constructor.app.ui.widgets import run_list_widget
    from agent_desktop_constructor.app.ui.widgets.run_list_widget import RunListWidget

    monkeypatch.setattr(run_list_widget, "show_info", lambda *args, **kwargs: None)
    container = FakeUiContainer()
    widget = RunListWidget(container)
    widget._run_manager = FakeSynchronousRunManager()
    widget.agent_id_edit.setText("agent-1")

    widget.show_runs()
    widget.run_agent()

    assert container.agent_service.calls == [
        "list_runs:agent-1",
        "run_agent:agent-1",
    ]


def test_run_events_widget_uses_service_event_api(qt_app) -> None:
    """Страница событий читает события через service API."""
    from agent_desktop_constructor.app.ui.widgets.run_events_widget import (
        RunEventsWidget,
    )

    container = FakeUiContainer()
    widget = RunEventsWidget(container)
    widget.run_id_edit.setText("run-1")

    widget.show_events()

    assert container.agent_service.calls == ["list_run_events:run-1"]
    assert widget.table.rowCount() == 1


def test_approval_queue_uses_service_resume_by_approval(qt_app, monkeypatch) -> None:
    """Страница подтверждений использует resume_run_by_approval."""
    from agent_desktop_constructor.app.ui.widgets import approval_queue_widget
    from agent_desktop_constructor.app.ui.widgets.approval_queue_widget import (
        ApprovalQueueWidget,
    )

    monkeypatch.setattr(approval_queue_widget, "show_info", lambda *args, **kwargs: None)
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

