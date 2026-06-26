"""Тесты runtime factory."""

from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.runtime.runtime_factory import build_runtime
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def test_build_runtime_returns_simple_agent_runtime() -> None:
    """build_runtime возвращает SimpleAgentRuntime."""
    gateway = ToolGateway(ToolRegistry())

    runtime = build_runtime(AppConfig(), gateway)

    assert isinstance(runtime, SimpleAgentRuntime)


def test_build_runtime_uses_passed_tool_gateway() -> None:
    """Runtime использует переданный ToolGateway."""
    gateway = ToolGateway(ToolRegistry())

    runtime = build_runtime(AppConfig(), gateway)

    assert runtime._tool_gateway is gateway

