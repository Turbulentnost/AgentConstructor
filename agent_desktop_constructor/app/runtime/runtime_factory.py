"""Фабрика runtime приложения."""

from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.gateway import ToolGateway


def build_runtime(
    config: AppConfig,
    tool_gateway: ToolGateway,
    run_repository: object | None = None,
    audit_repository: object | None = None,
    run_event_repository: object | None = None,
    human_approval_repository: object | None = None,
) -> SimpleAgentRuntime:
    """Собрать SimpleAgentRuntime с переданным ToolGateway."""
    _ = config
    return SimpleAgentRuntime(
        tool_gateway,
        run_repository=run_repository,
        audit_repository=audit_repository,
        run_event_repository=run_event_repository,
        human_approval_repository=human_approval_repository,
    )

