"""Bootstrap приложения: единая сборка зависимостей."""

from dataclasses import dataclass

from agent_desktop_constructor.app.builder.builder_factory import build_agent_builder
from agent_desktop_constructor.app.core.config import AppConfig, load_app_config_from_env
from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.app.runtime.runtime_factory import build_runtime
from agent_desktop_constructor.app.tools.tool_registry_factory import build_tool_registry
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.catalog import ToolsCatalog
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ApplicationContainer:
    """Собранные зависимости приложения."""

    config: AppConfig
    tools_catalog: ToolsCatalog
    agent_builder: AgentBuilder
    tool_registry: ToolRegistry
    tool_gateway: ToolGateway
    runtime: SimpleAgentRuntime
    agent_service: AgentApplicationService


def build_application_container(
    config: AppConfig | None = None,
) -> ApplicationContainer:
    """Собрать ApplicationContainer без запуска инструментов, агента и COM."""
    app_config = config or load_app_config_from_env()
    agent_builder = build_agent_builder(app_config)
    tools_catalog = agent_builder.tools_catalog
    tool_registry = build_tool_registry(app_config)
    tool_gateway = ToolGateway(tool_registry)
    runtime = build_runtime(app_config, tool_gateway)
    agent_service = AgentApplicationService(
        agent_builder=agent_builder,
        runtime=runtime,
        agent_repository=None,  # TODO: подключить SQLite repositories на composition root.
        run_repository=None,
        audit_repository=None,
    )

    return ApplicationContainer(
        config=app_config,
        tools_catalog=tools_catalog,
        agent_builder=agent_builder,
        tool_registry=tool_registry,
        tool_gateway=tool_gateway,
        runtime=runtime,
        agent_service=agent_service,
    )

