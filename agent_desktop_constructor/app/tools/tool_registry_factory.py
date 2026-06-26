"""Фабрика ToolRegistry для разных режимов запуска приложения."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.tools.com_backed_tools import register_outlook_com_tools
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeReportBuildTaskReportTool,
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.onec_tools import register_onec_readonly_tools
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.onec_worker import OneCReadOnlyWorker
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def build_tool_registry(config: AppConfig) -> ToolRegistry:
    """Собрать ToolRegistry без вызова инструментов и COM."""
    registry = ToolRegistry()

    if config.run_mode == AppRunMode.FAKE:
        register_fake_task_control_tools(registry)
        register_onec_readonly_tools(
            registry,
            OneCReadOnlyWorker(),
            skip_existing=True,
        )
        return registry

    if config.run_mode == AppRunMode.OUTLOOK_READONLY:
        worker = SubprocessComWorker()
        register_outlook_com_tools(registry, worker)
        register_onec_readonly_tools(registry, OneCReadOnlyWorker())
        _apply_com_timeout(registry, config)
        registry.register(FakeReportBuildTaskReportTool())
        return registry

    if config.run_mode == AppRunMode.OFFLINE:
        register_fake_task_control_tools(registry)
        register_onec_readonly_tools(
            registry,
            OneCReadOnlyWorker(),
            skip_existing=True,
        )
        return registry

    raise ValueError(f"Неизвестный run_mode: {config.run_mode}")


def _apply_com_timeout(registry: ToolRegistry, config: AppConfig) -> None:
    """Применить timeout AppConfig к COM-backed tools."""
    for tool_name in registry.list_tool_names():
        tool = registry.get(tool_name)
        tool.definition.timeout_seconds = config.com_worker_timeout_seconds

