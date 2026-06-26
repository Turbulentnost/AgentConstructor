"""Тесты реестра инструментов."""

import pytest

from agent_desktop_constructor.core.models.tooling import ToolDefinition
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.fake_tools import (
    FakeDangerousTool,
    FakeReadTool,
)
from agent_desktop_constructor.tools.registry import ToolRegistry


class ExecuteTrackingTool(FakeReadTool):
    """Fake-инструмент, фиксирующий факт вызова execute."""

    def __init__(self) -> None:
        """Создать инструмент с флагом вызова execute."""
        super().__init__()
        self.was_executed = False

    def execute(self, input_data: dict):
        """Отметить вызов execute и вернуть результат родительского инструмента."""
        self.was_executed = True
        return super().execute(input_data)


def test_tool_registry_starts_empty() -> None:
    """ToolRegistry создается пустым."""
    registry = ToolRegistry()

    assert registry.list_tools() == []
    assert registry.list_tool_names() == set()


def test_fake_read_tool_can_be_registered() -> None:
    """FakeReadTool регистрируется."""
    registry = ToolRegistry()

    registry.register(FakeReadTool())

    assert registry.has_tool("fake.read") is True


def test_get_returns_fake_read_tool() -> None:
    """get('fake.read') возвращает FakeReadTool."""
    registry = ToolRegistry()
    registry.register(FakeReadTool())

    tool = registry.get("fake.read")

    assert isinstance(tool, FakeReadTool)


def test_has_tool_returns_true_for_registered_tool() -> None:
    """has_tool('fake.read') возвращает True."""
    registry = ToolRegistry()
    registry.register(FakeReadTool())

    assert registry.has_tool("fake.read") is True


def test_has_tool_returns_false_for_unknown_tool() -> None:
    """has_tool('unknown') возвращает False."""
    registry = ToolRegistry()

    assert registry.has_tool("unknown") is False


def test_list_tools_returns_tool_definitions() -> None:
    """list_tools возвращает ToolDefinition."""
    registry = ToolRegistry()
    registry.register(FakeReadTool())

    definitions = registry.list_tools()

    assert len(definitions) == 1
    assert isinstance(definitions[0], ToolDefinition)


def test_list_tool_names_returns_registered_name() -> None:
    """list_tool_names возвращает имя fake.read."""
    registry = ToolRegistry()
    registry.register(FakeReadTool())

    assert registry.list_tool_names() == {"fake.read"}


def test_duplicate_registration_raises_error() -> None:
    """Повторная регистрация инструмента с тем же именем вызывает ошибку."""
    registry = ToolRegistry()
    registry.register(FakeReadTool())

    with pytest.raises(ValueError, match="fake.read"):
        registry.register(FakeReadTool())


def test_get_unknown_tool_raises_clear_error() -> None:
    """get('unknown') вызывает понятную ошибку."""
    registry = ToolRegistry()

    with pytest.raises(KeyError, match="unknown"):
        registry.get("unknown")


def test_registry_does_not_execute_tool_during_registration() -> None:
    """Registry не вызывает execute при регистрации."""
    registry = ToolRegistry()
    tool = ExecuteTrackingTool()

    registry.register(tool)

    assert tool.was_executed is False


def test_fake_dangerous_tool_can_be_registered_with_human_approval() -> None:
    """FakeDangerousTool можно зарегистрировать, если он требует HumanApproval."""
    registry = ToolRegistry()

    registry.register(FakeDangerousTool())

    assert registry.get("fake.dangerous").definition.requires_human_approval is True


def test_register_rejects_non_base_tool() -> None:
    """register отклоняет объект, который не является BaseTool."""
    registry = ToolRegistry()

    with pytest.raises(TypeError, match="BaseTool"):
        registry.register(object())  # type: ignore[arg-type]


def test_registered_tool_is_base_tool() -> None:
    """Зарегистрированный fake-инструмент является BaseTool."""
    registry = ToolRegistry()
    registry.register(FakeReadTool())

    assert isinstance(registry.get("fake.read"), BaseTool)
