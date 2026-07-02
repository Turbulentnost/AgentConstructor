"""Тесты фабрики ToolRegistry."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.tools.tool_registry_factory import build_tool_registry
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeOutlookSearchMailTool,
)


def test_fake_mode_registers_fake_tools() -> None:
    """fake mode регистрирует fake tools."""
    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.FAKE))

    assert registry.has_tool("outlook.search_mail")
    assert registry.has_tool("outlook.read_tasks")
    assert registry.has_tool("report.build_task_report")
    assert registry.has_tool("browser.search_web")
    assert registry.has_tool("browser.open_page")
    assert registry.has_tool("browser.extract_table")
    assert registry.has_tool("browser.scroll_page")
    assert registry.has_tool("browser.click_link")


def test_outlook_readonly_mode_registers_search_mail() -> None:
    """outlook_readonly mode регистрирует outlook.search_mail."""
    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.OUTLOOK_READONLY))

    assert registry.has_tool("outlook.search_mail")
    assert registry.has_tool("browser.search_web")
    assert registry.has_tool("browser.open_page")
    assert registry.has_tool("browser.extract_table")
    assert registry.has_tool("browser.scroll_page")
    assert registry.has_tool("browser.click_link")


def test_outlook_readonly_mode_registers_read_calendar() -> None:
    """outlook_readonly mode регистрирует outlook.read_calendar."""
    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.OUTLOOK_READONLY))

    assert registry.has_tool("outlook.read_calendar")


def test_outlook_readonly_mode_registers_blocked_email_send() -> None:
    """email.send зарегистрирован как dangerous и требует approval."""
    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.OUTLOOK_READONLY))
    definition = registry.get("email.send").definition

    assert definition.side_effect_level == ToolSideEffectLevel.DANGEROUS
    assert definition.requires_human_approval is True


def test_factory_does_not_call_execute(monkeypatch) -> None:
    """Factory только регистрирует tools и не вызывает execute."""

    def fail_execute(self, input_data):
        raise AssertionError("execute не должен вызываться при build_tool_registry")

    monkeypatch.setattr(FakeOutlookSearchMailTool, "execute", fail_execute)

    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.FAKE))

    assert registry.has_tool("outlook.search_mail")


def test_outlook_readonly_factory_does_not_require_outlook() -> None:
    """Сборка outlook_readonly registry не требует запущенного Outlook."""
    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.OUTLOOK_READONLY))

    assert registry.has_tool("email.send")
    assert registry.has_tool("report.build_task_report")

