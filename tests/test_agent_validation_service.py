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
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.com_backed_tools import register_outlook_com_tools
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.report_tools import register_report_tools
from agent_desktop_constructor.workers.models import WorkerResult


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
        make_agent_spec_without_tools(),
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
        make_agent_spec_without_tools(),
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

    result = service.validate_agent(make_agent_spec_without_tools(), "Найди совещания")

    assert result.status == AgentValidationStatus.PASSED
    assert result.final_message == "Итоговые рекомендации готовы"
    assert result.output_data == {"summary": "summary"}


def test_validation_service_uses_com_read_tool_and_analysis_output() -> None:
    """Validation проходит через COM-backed read tool и аналитический вывод."""
    registry = ToolRegistry()
    com_worker = FakeComWorker()
    analysis_tool = FakeLlmAnalyzeCollectedDataTool()
    register_outlook_com_tools(registry, com_worker)
    registry.register(analysis_tool)
    register_report_tools(registry)
    runtime = SimpleAgentRuntime(ToolGateway(registry))
    service = AgentValidationService(
        agent_service=None,
        runtime=runtime,
        tool_registry=registry,
        tools_catalog=load_tools_catalog(),
    )
    agent_spec = AgentBuilder().build_from_request(
        "Нужен агент, который смотрит все совещания в Outlook и выводит как лучше распланировать график"
    )

    result = service.validate_agent(agent_spec, "распланировать график по Outlook")

    assert result.status == AgentValidationStatus.PASSED
    assert com_worker.called_tool_names == ["outlook.read_calendar"]
    assert analysis_tool.received_calendar_events
    assert result.output_data is not None
    assert result.output_data["meeting_count"] == 1
    assert "Сгруппировать короткие встречи" in result.final_message


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


class FakeComWorker:
    """Mock COM worker, который имитирует read-only чтение календаря Outlook."""

    def __init__(self) -> None:
        self.called_tool_names: list[str] = []

    def execute(self, task):
        """Вернуть данные календаря в формате COM worker result."""
        self.called_tool_names.append(task.tool_name)
        return WorkerResult(
            task_id=task.task_id,
            ok=True,
            output_data={
                "events": [
                    {
                        "id": "event-com-1",
                        "title": "Планёрка проекта",
                        "start_at": "2026-07-02T10:00:00",
                        "participants": ["Иванов И.И.", "Петров П.П."],
                    }
                ],
                "count": 1,
                "source": "outlook_com",
            },
        )


class FakeLlmAnalyzeCollectedDataTool(BaseTool):
    """LLM-analysis stub, проверяющий доступность COM output для выводов."""

    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="llm.analyze_collected_data",
                title="Анализ собранных данных",
                description="Тестовый LLM-анализ собранных данных.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LLM,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )
        self.received_calendar_events = False

    def execute(self, input_data: dict) -> ToolCallResult:
        """Сделать вывод только если получил результат outlook.read_calendar."""
        calendar_output = input_data.get("tool_outputs", {}).get("outlook.read_calendar")
        events = calendar_output.get("events", []) if isinstance(calendar_output, dict) else []
        self.received_calendar_events = bool(events)
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "summary": "Календарь прочитан через COM worker, найдено 1 совещание.",
                "findings": ["Есть утренняя планёрка"],
                "risks": ["После планёрки нужен слот на фокус-работу"],
                "recommendations": ["Оставить 90 минут после планёрки"],
                "confidence": 0.9,
            },
        )


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


def make_agent_spec_without_tools() -> AgentSpec:
    """Создать AgentSpec без обязательных tool_call узлов."""
    return AgentSpec(
        agent_id="agent-no-tools",
        name="No tools agent",
        description="No tools agent",
        goal=AgentGoal(
            main_goal="Сформировать ответ",
            success_criteria=["Ответ сформирован"],
            forbidden_actions=["Не выполнять tools"],
        ),
        data_requirements=[],
        tools=[],
        graph_nodes=[
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Final",
                description="Final",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            )
        ],
        runtime_limits=AgentRuntimeLimits(),
    )

