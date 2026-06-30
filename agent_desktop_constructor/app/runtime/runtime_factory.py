"""Фабрика runtime приложения."""

from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.models.agent_build_mode import AgentBuildMode
from agent_desktop_constructor.app.llm.supervisor import LLMSupervisor
from agent_desktop_constructor.app.runtime.supervised_runtime import SupervisedAgentRuntime
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.catalog import ToolsCatalog
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def build_runtime(
    config: AppConfig,
    tool_gateway: ToolGateway,
    tools_catalog: ToolsCatalog | None = None,
    tool_registry: ToolRegistry | None = None,
    run_repository: object | None = None,
    audit_repository: object | None = None,
    run_event_repository: object | None = None,
    human_approval_repository: object | None = None,
    llm_supervisor: LLMSupervisor | None = None,
    credential_request_repository: object | None = None,
) -> SimpleAgentRuntime:
    """Собрать runtime с переданным ToolGateway."""
    if config.agent_build_mode == AgentBuildMode.LLM_SUPERVISED:
        return SupervisedAgentRuntime(
            tool_gateway=tool_gateway,
            llm_supervisor=llm_supervisor,
            tools_catalog=tools_catalog,
            tool_registry=tool_registry,
            run_repository=run_repository,
            audit_repository=audit_repository,
            run_event_repository=run_event_repository,
            human_approval_repository=human_approval_repository,
            credential_request_repository=credential_request_repository,
        )
    return SimpleAgentRuntime(
        tool_gateway,
        run_repository=run_repository,
        audit_repository=audit_repository,
        run_event_repository=run_event_repository,
        human_approval_repository=human_approval_repository,
    )

