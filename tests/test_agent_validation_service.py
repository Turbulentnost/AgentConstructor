"""Тесты AgentValidationService."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.models.agent_validation import (
    AgentValidationStatus,
)
from agent_desktop_constructor.app.core.services.agent_validation_service import (
    AgentValidationService,
)
from agent_desktop_constructor.app.runtime.runtime_factory import build_runtime
from agent_desktop_constructor.app.tools.tool_registry_factory import build_tool_registry
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    HumanApprovalRequest,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def make_validation_service(config: AppConfig) -> AgentValidationService:
    """Создать validation service с fake registry."""
    registry = build_tool_registry(config)
    runtime = build_runtime(config, ToolGateway(registry))
    return AgentValidationService(
        agent_service=None,
        runtime=runtime,
        tool_registry=registry,
        tools_catalog=load_tools_catalog(),
    )


def test_validation_service_runs_trial_run_for_fake_meeting_agent() -> None:
    """Validation passed для fake meeting agent."""
    config = AppConfig(run_mode=AppRunMode.FAKE)
    agent_spec = AgentBuilder().build_from_request(
        "Нужен агент, который смотрит все совещания и планирует график"
    )

    result = make_validation_service(config).validate_agent(agent_spec, "совещания")

    assert result.status == AgentValidationStatus.PASSED
    assert result.run_id is not None
    assert result.final_message
    assert result.output_data is not None
    assert "recommendations" in result.output_data


def test_validation_service_fails_on_missing_tool() -> None:
    """Validation failed при missing tool."""
    config = AppConfig(run_mode=AppRunMode.FAKE)
    agent_spec = AgentBuilder().build_from_request("Проанализируй документ")

    result = make_validation_service(config).validate_agent(agent_spec, "документ")

    assert result.status == AgentValidationStatus.FAILED
    assert any("не зарегистрирован" in error for error in result.errors)


def test_validation_service_fails_on_unknown_llm_tool() -> None:
    """Unknown LLM tool даёт failed через ToolsCatalog."""
    config = AppConfig(run_mode=AppRunMode.FAKE)
    agent_spec = make_agent_spec_with_tool("invented.tool")

    result = make_validation_service(config).validate_agent(agent_spec, "bad")

    assert result.status == AgentValidationStatus.FAILED
    assert any("invented.tool" in error for error in result.errors)


def test_validation_service_returns_needs_human() -> None:
    """HumanApproval даёт needs_human."""
    service = make_service_with_fake_runtime(
        AgentRuntimeState(
            run_id="run-human",
            agent_id="agent-1",
            status=AgentRunStatus.PAUSED_FOR_HUMAN,
            pending_human_approval=HumanApprovalRequest(
                approval_id="approval-1",
                node_id="node-1",
                question="Продолжить?",
                options=["Да", "Нет"],
                status="pending",
            ),
        )
    )

    result = service.validate_agent(
        AgentBuilder().build_from_request("Найди совещания"),
        "Найди совещания",
    )

    assert result.status == AgentValidationStatus.NEEDS_HUMAN


def test_validation_service_returns_needs_credentials() -> None:
    """CredentialRequest даёт needs_credentials."""
    service = make_service_with_fake_runtime(
        AgentRuntimeState(
            run_id="run-credentials",
            agent_id="agent-1",
            status=AgentRunStatus.PAUSED_FOR_CREDENTIALS,
            variables={"credential_request_reason": "ONEC_AUTH_REQUIRED"},
        )
    )

    result = service.validate_agent(
        AgentBuilder().build_from_request("Найди совещания"),
        "Найди совещания",
    )

    assert result.status == AgentValidationStatus.NEEDS_CREDENTIALS


def test_validation_service_returns_final_output_from_runtime_state() -> None:
    """ValidationResult содержит итоговый вывод из final_message/output_data."""
    service = make_service_with_fake_runtime(
        AgentRuntimeState(
            run_id="run-output",
            agent_id="agent-1",
            status=AgentRunStatus.COMPLETED,
            variables={
                "final_message": "Итоговые рекомендации готовы",
                "tool_outputs": {"tool": {"summary": "summary"}},
            },
        )
    )

    result = service.validate_agent(
        AgentBuilder().build_from_request("Найди совещания"),
        "Найди совещания",
    )

    assert result.status == AgentValidationStatus.PASSED
    assert result.final_message == "Итоговые рекомендации готовы"
    assert result.output_data == {"summary": "summary"}


class FakeValidationRuntime:
    """Runtime stub для статусов validation."""

    def __init__(self, state: AgentRuntimeState) -> None:
        self.state = state
        self.calls = 0
        self.last_initial_variables = None

    def run(self, agent_spec, initial_variables=None, run_id=None):
        """Вернуть заданное состояние."""
        self.calls += 1
        self.last_initial_variables = initial_variables
        self.state.agent_id = agent_spec.agent_id
        return self.state


def make_service_with_fake_runtime(state: AgentRuntimeState) -> AgentValidationService:
    """Создать validation service с fake runtime."""
    config = AppConfig(run_mode=AppRunMode.FAKE)
    registry = build_tool_registry(config)
    return AgentValidationService(
        agent_service=None,
        runtime=FakeValidationRuntime(state),
        tool_registry=registry,
        tools_catalog=load_tools_catalog(),
    )


def make_agent_spec_with_tool(tool_name: str) -> AgentSpec:
    """Создать AgentSpec с произвольным tool_name."""
    return AgentSpec(
        agent_id="agent-unknown-tool",
        name="Unknown tool agent",
        description="Unknown tool agent",
        goal=AgentGoal(
            main_goal="Проверить unknown tool",
            success_criteria=["Проверено"],
            forbidden_actions=["Не исполнять unknown"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name=tool_name,
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            )
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="call_unknown",
                node_type=AgentGraphNodeType.TOOL_CALL,
                title="Call unknown",
                description="Call unknown",
                tool_name=tool_name,
                next_on_success="final",
                next_on_error="final_failed",
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Final",
                description="Final",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final_failed",
                node_type=AgentGraphNodeType.FINAL,
                title="Failed",
                description="Failed",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
        ],
        runtime_limits=AgentRuntimeLimits(),
    )

