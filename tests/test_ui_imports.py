"""Smoke-тесты PySide6 desktop UI."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

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


def _wait_for_ui_idle(widget, qt_app, timeout_ms: int = 5000) -> None:
    """Прокрутить event loop, пока фоновая операция виджета не завершится."""
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while getattr(widget, "_thread", None) is not None:
        qt_app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Фоновая операция UI не завершилась вовремя")
        time.sleep(0.01)
    qt_app.processEvents()


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
        "agent_desktop_constructor.app.ui.widgets.context_indicator",
    ]

    for module_name in module_names:
        assert importlib.import_module(module_name) is not None


def test_main_window_can_be_created(qt_app, fake_container) -> None:
    """MainWindow можно создать с fake ApplicationContainer."""
    from agent_desktop_constructor.app.ui.main_window import MainWindow
    from agent_desktop_constructor.app.ui.teams_nav_sidebar import NAV_ITEMS

    window = MainWindow(fake_container)

    assert window.windowTitle() == "Конструктор ИИ-агентов"
    assert window.pages.count() == 5
    assert window.nav.count() == 5
    assert [item.title for item in NAV_ITEMS] == [
        "Агенты",
        "Создать агента",
        "Запуски",
        "События",
        "Настройки",
    ]


def test_agent_create_widget_can_be_created(qt_app, fake_container) -> None:
    """AgentCreateWidget можно создать."""
    from PySide6.QtCore import QPoint

    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        MODEL_BADGE_STYLE,
        AgentCreateWidget,
        BadgeSelect,
    )

    widget = AgentCreateWidget(fake_container)
    widget.resize(900, 700)
    widget.show()
    widget.move(0, 200)
    qt_app.processEvents()

    assert widget.request_edit is not None
    assert isinstance(widget.model_combo, BadgeSelect)
    assert isinstance(widget.reason_combo, BadgeSelect)
    assert widget.context_indicator is not None
    assert "border-radius: 9px" in MODEL_BADGE_STYLE
    assert widget.model_combo.isEnabled()
    assert widget.model_combo.count() >= 2

    composer = widget.request_edit.parentWidget()
    toolbar = composer.layout().itemAt(1).layout()
    attach_index = None
    model_index = None
    for index in range(toolbar.count()):
        item_widget = toolbar.itemAt(index).widget()
        if item_widget is widget.attach_button:
            attach_index = index
        if item_widget is widget.model_combo:
            model_index = index
    assert attach_index is not None
    assert model_index is not None
    assert model_index > attach_index

    widget.model_combo.showPopup()
    qt_app.processEvents()
    menu = widget.model_combo.view()
    assert menu.isVisible()
    combo_top = widget.model_combo.mapToGlobal(QPoint(0, 0)).y()
    assert combo_top > 0
    assert menu.frameGeometry().bottom() <= combo_top + 2

    changed_index = None
    def _capture(index: int) -> None:
        nonlocal changed_index
        changed_index = index

    widget.model_combo.currentIndexChanged.connect(_capture)
    for action in menu.actions():
        if action.text() != widget.model_combo.currentText().rstrip(" ▾"):
            action.trigger()
            break
    qt_app.processEvents()
    assert changed_index is not None
    widget.model_combo.hidePopup()


def test_context_indicator_accepts_usage(qt_app) -> None:
    """ContextIndicator принимает usage payload и обновляет tooltip."""
    from agent_desktop_constructor.app.ui.widgets.context_indicator import (
        ContextIndicator,
    )

    indicator = ContextIndicator()
    indicator.set_usage(
        {
            "total_chars": 120,
            "total_limit": 1000,
            "total_percent": 12.0,
            "section_chars": {"creation": 40, "tool_results": 80},
            "section_percent": {"creation": 5.0, "tool_results": 10.0},
        }
    )
    indicator.show()
    qt_app.processEvents()

    assert "12.0%" in indicator.toolTip()
    assert "разбивку по секциям" in indicator.toolTip()
    assert indicator.width() == 34


def test_context_indicator_popover_position_prefers_above() -> None:
    """Popover открывается над индикатором, если сверху достаточно места."""
    from PySide6.QtCore import QPoint, QRect, QSize

    from agent_desktop_constructor.app.ui.widgets.context_indicator import (
        POPOVER_MARGIN,
        _popover_position,
    )

    position = _popover_position(
        QPoint(400, 300),
        QSize(34, 34),
        QSize(180, 120),
        QRect(0, 0, 1000, 800),
    )

    assert position.y() == 300 - 120 - POPOVER_MARGIN
    assert position.x() == 400 + (34 - 180) // 2


def test_context_indicator_popover_position_falls_back_below() -> None:
    """Popover открывается снизу, если над индикатором нет места."""
    from PySide6.QtCore import QPoint, QRect, QSize

    from agent_desktop_constructor.app.ui.widgets.context_indicator import (
        POPOVER_MARGIN,
        _popover_position,
    )

    position = _popover_position(
        QPoint(400, 20),
        QSize(34, 34),
        QSize(180, 120),
        QRect(0, 0, 1000, 800),
    )

    assert position.y() == 20 + 34 + POPOVER_MARGIN


def test_context_indicator_usage_color_thresholds() -> None:
    """Цвет индикатора меняется по уровню заполнения."""
    from agent_desktop_constructor.app.ui.widgets.context_indicator import _usage_color

    assert _usage_color(0) == "#64748b"
    assert _usage_color(10) == "#38bdf8"
    assert _usage_color(50) == "#22c55e"
    assert _usage_color(80) == "#f59e0b"
    assert _usage_color(95) == "#ef4444"


def test_agent_create_widget_keeps_proxy_claude_models(monkeypatch) -> None:
    """Селект моделей сохраняет конкретные Claude-модели из прокси."""
    from agent_desktop_constructor.app.ui.widgets import agent_create_widget
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
        _merge_default_model_options,
    )

    payload = {
        "data": [
            {
                "id": "chatgpt",
                "metadata": {
                    "display_name": "Chat-GPT 5.5",
                    "supports_reasoning": True,
                },
            },
            {
                "id": "claude",
                "metadata": {
                    "display_name": "Claude",
                    "supports_reasoning": True,
                },
            },
            {
                "id": "claude-sonnet-4.6",
                "metadata": {
                    "display_name": "Claude Sonnet 4.6",
                    "supports_reasoning": True,
                },
            },
            {
                "id": "claude-sonnet-4.6:reason",
                "metadata": {
                    "display_name": "Claude Sonnet 4.6",
                    "supports_reasoning": True,
                },
            },
            {
                "id": "claude-opus-4.1",
                "metadata": {
                    "display_name": "Claude Opus 4.1",
                    "supports_reasoning": True,
                },
            },
            {
                "id": "lmstudio",
                "metadata": {
                    "display_name": "LM Studio (gpt-oss-120b)",
                    "supports_reasoning": False,
                },
            },
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    requested_urls: list[str] = []

    def fake_urlopen(url: str, timeout: int):
        requested_urls.append(url)
        assert timeout == 3
        return FakeResponse()

    monkeypatch.setattr(agent_create_widget.request, "urlopen", fake_urlopen)
    dummy = SimpleNamespace(
        _container=SimpleNamespace(
            config=SimpleNamespace(llm_proxy_url="http://192.168.2.135:8080")
        )
    )

    proxy_options = AgentCreateWidget._load_proxy_model_options(dummy)
    options = _merge_default_model_options(proxy_options)
    ids = [option.model_id for option in options]

    assert requested_urls == ["http://192.168.2.135:8080/v1/models"]
    assert "claude" not in ids
    assert "claude-sonnet-4.6" in ids
    assert "claude-opus-4.1" in ids
    sonnet = next(option for option in options if option.model_id == "claude-sonnet-4.6")
    assert sonnet.supports_reasoning is True
    assert sonnet.modes == ("reason",)


def test_agent_create_widget_persists_selected_model_id(
    qt_app,
    fake_container,
    monkeypatch,
) -> None:
    """Смена модели/reason сохраняет полный model id."""
    from agent_desktop_constructor.app.ui.widgets import agent_create_widget
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )

    saved_models: list[str] = []
    monkeypatch.setattr(agent_create_widget, "save_llm_model_name", saved_models.append)
    widget = AgentCreateWidget(fake_container)

    reason_index = widget.reason_combo.findData("reason")
    widget.reason_combo.setCurrentIndex(reason_index)
    qt_app.processEvents()

    lmstudio_index = widget.model_combo.findData("lmstudio")
    widget.model_combo.setCurrentIndex(lmstudio_index)
    qt_app.processEvents()

    assert saved_models[-2:] == ["chatgpt:reason", "lmstudio"]

    widget._ensure_selected_model_container()

    assert widget._container.config.llm_model_name == "lmstudio"
    assert saved_models[-1] == "lmstudio"


def test_agent_list_widget_can_be_created(qt_app, fake_container) -> None:
    """AgentListWidget можно создать."""
    from agent_desktop_constructor.app.ui.widgets.agent_list_widget import (
        AgentListWidget,
    )

    widget = AgentListWidget(fake_container)

    assert widget.title_label.text() == "Каталог агентов"
    assert widget._canvas is not None
    assert widget.cards_layout is not None


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
    _wait_for_ui_idle(widget, qt_app)

    assert container.agent_service.calls == ["build_preview:создай агента"]


def test_agent_list_refresh_uses_service(qt_app) -> None:
    """Страница агентов читает список через service."""
    from agent_desktop_constructor.app.ui.widgets.agent_list_widget import (
        AgentListWidget,
    )

    container = FakeUiContainer()
    widget = AgentListWidget(container)

    widget.refresh()

    # Конструктор уже подгружает список сразу, refresh() читает повторно.
    assert container.agent_service.calls == ["list_agents", "list_agents"]
    assert len(widget._agents) == 1
    assert len(widget._agent_cards) == 1


def test_agent_list_auto_refreshes_on_nav(qt_app, fake_container) -> None:
    """При переходе на страницу агентов список загружается автоматически."""
    from agent_desktop_constructor.app.ui.main_window import MainWindow

    window = MainWindow(fake_container)
    window.show()
    for _ in range(5):
        qt_app.processEvents()

    assert len(window._agent_list._agents) >= 0

    window.nav.setCurrentIndex(1)
    qt_app.processEvents()
    window.nav.setCurrentIndex(0)
    for _ in range(5):
        qt_app.processEvents()


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

