"""Фабрика ToolRegistry для разных режимов запуска приложения."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.core.models.tooling import ToolExecutionMode
from agent_desktop_constructor.app.llm.client_factory import build_llm_client
from agent_desktop_constructor.app.tools.llm_analysis_tools import (
    register_llm_analysis_tools,
)
from agent_desktop_constructor.tools.agent_workspace import AgentWorkspaceResolver
from agent_desktop_constructor.tools.code_execution_tools import (
    register_code_execution_tools,
)
from agent_desktop_constructor.tools.com_backed_tools import register_outlook_com_tools
from agent_desktop_constructor.tools.excel_tools import register_excel_tools
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.onec_tools import register_onec_readonly_tools
from agent_desktop_constructor.tools.powershell_tools import register_powershell_tools
from agent_desktop_constructor.tools.report_tools import register_report_tools
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.wait_tool import register_wait_tool
from agent_desktop_constructor.tools.web_tools import register_web_tools
from agent_desktop_constructor.workers.onec_worker import OneCReadOnlyWorker
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def build_tool_registry(config: AppConfig) -> ToolRegistry:
    """Собрать ToolRegistry без вызова инструментов и COM."""
    registry = ToolRegistry()
    workspace_resolver = AgentWorkspaceResolver(config.resolve_agent_workspaces_root())

    if config.run_mode == AppRunMode.FAKE:
        register_fake_task_control_tools(registry)
        register_report_tools(registry, skip_existing=True)
        register_onec_readonly_tools(
            registry,
            OneCReadOnlyWorker(),
            skip_existing=True,
        )
        register_web_tools(
            registry, skip_existing=True, workspace_resolver=workspace_resolver
        )
        register_excel_tools(registry, workspace_resolver, skip_existing=True)
        register_powershell_tools(registry, workspace_resolver, skip_existing=True)
        register_code_execution_tools(registry, workspace_resolver, skip_existing=True)
        register_wait_tool(registry, skip_existing=True)
        return registry

    if config.run_mode == AppRunMode.OUTLOOK_READONLY:
        worker = SubprocessComWorker()
        register_outlook_com_tools(registry, worker)
        register_onec_readonly_tools(registry, OneCReadOnlyWorker())
        register_report_tools(registry, skip_existing=True)
        register_web_tools(
            registry, skip_existing=True, workspace_resolver=workspace_resolver
        )
        if config.use_llm_planner:
            register_llm_analysis_tools(
                registry,
                build_llm_client(config.to_llm_config()),
                skip_existing=True,
            )
        _apply_com_timeout(registry, config)
        register_excel_tools(registry, workspace_resolver, skip_existing=True)
        register_powershell_tools(registry, workspace_resolver, skip_existing=True)
        register_code_execution_tools(registry, workspace_resolver, skip_existing=True)
        register_wait_tool(registry, skip_existing=True)
        return registry

    if config.run_mode == AppRunMode.OFFLINE:
        register_fake_task_control_tools(registry)
        register_report_tools(registry, skip_existing=True)
        register_onec_readonly_tools(
            registry,
            OneCReadOnlyWorker(),
            skip_existing=True,
        )
        register_web_tools(
            registry, skip_existing=True, workspace_resolver=workspace_resolver
        )
        register_excel_tools(registry, workspace_resolver, skip_existing=True)
        register_powershell_tools(registry, workspace_resolver, skip_existing=True)
        register_code_execution_tools(registry, workspace_resolver, skip_existing=True)
        register_wait_tool(registry, skip_existing=True)
        return registry

    raise ValueError(f"Неизвестный run_mode: {config.run_mode}")


def _apply_com_timeout(registry: ToolRegistry, config: AppConfig) -> None:
    """Применить timeout AppConfig к COM-backed tools."""
    for tool_name in registry.list_tool_names():
        tool = registry.get(tool_name)
        if tool.definition.execution_mode != ToolExecutionMode.COM_WORKER:
            continue
        tool.definition.timeout_seconds = config.com_worker_timeout_seconds

