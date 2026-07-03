"""Тесты инструмента паузы агента (agent.wait)."""

from __future__ import annotations

from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.wait_tool import (
    MAX_WAIT_SECONDS,
    WAIT_TOOL_NAME,
    AgentWaitTool,
    register_wait_tool,
)


def test_wait_zero_seconds_returns_immediately() -> None:
    """Пауза 0 секунд успешна и ничего не ждёт."""
    tool = AgentWaitTool()

    result = tool.execute({"seconds": 0})

    assert result.ok
    assert result.output_data["waited_seconds"] == 0
    assert result.output_data["cancelled"] is False


def test_wait_rejects_non_numeric_seconds() -> None:
    """Некорректный seconds даёт понятную ошибку."""
    tool = AgentWaitTool()

    result = tool.execute({"seconds": "скоро"})

    assert not result.ok
    assert result.error_type == "INVALID_SECONDS"


def test_wait_rejects_negative_seconds() -> None:
    """Отрицательная пауза не допускается."""
    tool = AgentWaitTool()

    result = tool.execute({"seconds": -5})

    assert not result.ok
    assert result.error_type == "INVALID_SECONDS"


def test_wait_is_interrupted_by_cancel_check() -> None:
    """Пауза прерывается, если запрошена остановка агента."""
    tool = AgentWaitTool()
    tool.cancel_check = lambda: True

    result = tool.execute({"seconds": MAX_WAIT_SECONDS})

    assert result.ok
    assert result.output_data["cancelled"] is True
    assert result.output_data["waited_seconds"] < 1


def test_register_wait_tool_adds_to_registry() -> None:
    """Инструмент регистрируется под именем agent.wait."""
    registry = ToolRegistry()

    register_wait_tool(registry)

    assert registry.has_tool(WAIT_TOOL_NAME)
