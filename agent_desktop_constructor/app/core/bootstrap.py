"""Bootstrap приложения: единая сборка зависимостей."""

from dataclasses import dataclass

from agent_desktop_constructor.app.builder.builder_factory import build_agent_builder
from agent_desktop_constructor.app.core.config import AppConfig, load_app_config_from_env
from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.app.core.services.agent_validation_service import (
    AgentValidationService,
)
from agent_desktop_constructor.app.core.models.agent_build_mode import AgentBuildMode
from agent_desktop_constructor.app.llm.agent_loop_planner import LLMAgentLoopPlanner
from agent_desktop_constructor.app.llm.client_factory import build_llm_client
from agent_desktop_constructor.app.llm.supervisor import LLMSupervisor
from agent_desktop_constructor.app.runtime.runtime_factory import build_runtime
from agent_desktop_constructor.app.tools.tool_registry_factory import build_tool_registry
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.storage.database import (
    create_engine_for_sqlite,
    create_session_factory,
    init_database,
)
from agent_desktop_constructor.storage.repositories import (
    AgentRepository,
    AgentRunRepository,
    AuditLogRepository,
    HumanApprovalRepository,
    RunEventRepository,
    ToolCallLogRepository,
)
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
    session_factory: object
    agent_repository: AgentRepository
    run_repository: AgentRunRepository
    audit_repository: AuditLogRepository
    tool_call_log_repository: ToolCallLogRepository | None
    run_event_repository: RunEventRepository | None = None
    human_approval_repository: HumanApprovalRepository | None = None
    agent_validation_service: AgentValidationService | None = None


def build_application_container(
    config: AppConfig | None = None,
) -> ApplicationContainer:
    """Собрать ApplicationContainer без запуска инструментов, агента и COM."""
    app_config = config or load_app_config_from_env()
    engine = create_engine_for_sqlite(app_config.database_path)
    init_database(engine)
    session_factory = create_session_factory(engine)
    agent_repository = AgentRepository(session_factory)
    run_repository = AgentRunRepository(session_factory)
    audit_repository = AuditLogRepository(session_factory)
    run_event_repository = RunEventRepository(session_factory)
    human_approval_repository = HumanApprovalRepository(session_factory)
    tool_call_log_repository = ToolCallLogRepository(session_factory)

    agent_builder = build_agent_builder(app_config)
    tools_catalog = agent_builder.tools_catalog
    tool_registry = build_tool_registry(app_config)
    tool_gateway = ToolGateway(tool_registry)
    llm_supervisor = None
    agent_loop_planner = None
    if app_config.use_llm_planner:
        llm_client = build_llm_client(app_config.to_llm_config())
        llm_supervisor = LLMSupervisor(llm_client, tools_catalog)
        agent_loop_planner = LLMAgentLoopPlanner(llm_client, tools_catalog)
    runtime = build_runtime(
        app_config,
        tool_gateway,
        tools_catalog=tools_catalog,
        tool_registry=tool_registry,
        run_repository=run_repository,
        audit_repository=audit_repository,
        run_event_repository=run_event_repository,
        human_approval_repository=human_approval_repository,
        llm_supervisor=llm_supervisor,
        agent_loop_planner=agent_loop_planner,
    )
    agent_validation_service = AgentValidationService(
        agent_service=None,
        runtime=runtime,
        tool_registry=tool_registry,
        tools_catalog=tools_catalog,
        enforce_required_graph_tools=(
            app_config.agent_build_mode != AgentBuildMode.LLM_AGENT_LOOP
        ),
    )
    agent_service = AgentApplicationService(
        agent_builder=agent_builder,
        runtime=runtime,
        agent_repository=agent_repository,
        run_repository=run_repository,
        audit_repository=audit_repository,
        run_event_repository=run_event_repository,
        human_approval_repository=human_approval_repository,
        agent_validation_service=agent_validation_service,
    )

    return ApplicationContainer(
        config=app_config,
        tools_catalog=tools_catalog,
        agent_builder=agent_builder,
        tool_registry=tool_registry,
        tool_gateway=tool_gateway,
        runtime=runtime,
        agent_service=agent_service,
        session_factory=session_factory,
        agent_repository=agent_repository,
        run_repository=run_repository,
        audit_repository=audit_repository,
        run_event_repository=run_event_repository,
        human_approval_repository=human_approval_repository,
        tool_call_log_repository=tool_call_log_repository,
        agent_validation_service=agent_validation_service,
    )

