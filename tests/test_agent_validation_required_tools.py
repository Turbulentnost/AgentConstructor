"""Тесты проверки обязательных tool results в AgentValidationService."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.models.agent_validation import (
    AgentValidationStatus,
)
from agent_desktop_constructor.app.core.services.agent_validation_service import (
    AgentValidationService,
)
from agent_desktop_constructor.app.tools.tool_registry_factory import build_tool_registry
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
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class FakeRuntime:
    """Runtime, возвращающий заранее подготовленное состояние."""

    def __init__(self, state: AgentRuntimeState) -> None:
        self.state = state

    def run(self, agent_spec, initial_variables=None, run_id=None):
        """Вернуть state для validation."""
        self.state.agent_id = agent_spec.agent_id
        return self.state


def test_required_read_calendar_timeout_fails_validation() -> None:
    """outlook.read_calendar timeout => validation failed."""
    state = make_state()
    state.add_tool_result(
        tool_name="outlook.read_calendar",
        input_data={},
        output_data=None,
        ok=False,
        error_type="WORKER_TIMEOUT",
        error_message="timed out",
    )

    result = make_service(state).validate_agent(make_calendar_agent_spec(), "календарь")

    assert result.status == AgentValidationStatus.FAILED
    assert result.critical_errors == [
        "Обязательный инструмент outlook.read_calendar не получил данные: WORKER_TIMEOUT"
    ]
    assert result.tool_result_checks[0]["error_type"] == "WORKER_TIMEOUT"


def test_required_read_calendar_with_events_passes_validation() -> None:
    """outlook.read_calendar ok=True с events => validation passed."""
    state = make_state()
    state.add_tool_result(
        tool_name="outlook.read_calendar",
        input_data={},
        output_data={"events": [{"id": "event-1", "title": "Совещание"}]},
        ok=True,
    )
    state.variables["tool_outputs"] = {
        "outlook.read_calendar": {"events": [{"id": "event-1"}]}
    }

    result = make_service(state).validate_agent(make_calendar_agent_spec(), "календарь")

    assert result.status == AgentValidationStatus.PASSED
    assert result.critical_errors == []
    assert result.tool_result_checks[0]["critical"] is False


def test_report_output_cannot_pass_validation_when_read_calendar_failed() -> None:
    """report tool не может сделать validation passed, если read_calendar failed."""
    state = make_state()
    state.add_tool_result(
        tool_name="outlook.read_calendar",
        input_data={},
        output_data=None,
        ok=False,
        error_type="COM_NOT_AVAILABLE",
        error_message="COM unavailable",
    )
    state.add_tool_result(
        tool_name="report.build_schedule_recommendations",
        input_data={},
        output_data={"recommendation_text": "План готов"},
        ok=True,
    )
    state.variables["tool_outputs"] = {
        "report.build_schedule_recommendations": {
            "recommendation_text": "План готов"
        }
    }

    result = make_service(state).validate_agent(make_calendar_agent_spec(), "календарь")

    assert result.status == AgentValidationStatus.FAILED
    assert "COM_NOT_AVAILABLE" in result.critical_errors[0]


def test_timeout_warning_becomes_critical_error_for_required_tool() -> None:
    """warnings timeout отображаются как critical_errors для обязательных tools."""
    state = make_state()
    state.variables["supervisor_warnings"] = ["timed out"]

    result = make_service(state).validate_agent(make_calendar_agent_spec(), "календарь")

    assert result.status == AgentValidationStatus.FAILED
    assert result.critical_errors == [
        "Обязательный инструмент outlook.read_calendar не получил данные: WORKER_TIMEOUT"
    ]
    assert result.tool_result_checks[0]["error_type"] == "WORKER_TIMEOUT"


def test_required_read_calendar_empty_events_fails_validation() -> None:
    """Пустой events считается отсутствием полезных данных."""
    state = make_state()
    state.add_tool_result(
        tool_name="outlook.read_calendar",
        input_data={},
        output_data={"events": []},
        ok=True,
    )

    result = make_service(state).validate_agent(make_calendar_agent_spec(), "календарь")

    assert result.status == AgentValidationStatus.FAILED
    assert result.critical_errors == [
        "Обязательный инструмент outlook.read_calendar не вернул полезные данные"
    ]


def make_service(state: AgentRuntimeState) -> AgentValidationService:
    """Создать validation service с fake runtime."""
    registry = build_tool_registry(AppConfig(run_mode=AppRunMode.FAKE))
    return AgentValidationService(
        agent_service=None,
        runtime=FakeRuntime(state),
        tool_registry=registry,
        tools_catalog=load_tools_catalog(),
    )


def make_state() -> AgentRuntimeState:
    """Создать completed state для пробного запуска."""
    return AgentRuntimeState(
        run_id="run-1",
        agent_id="agent-1",
        status=AgentRunStatus.COMPLETED,
    )


def make_calendar_agent_spec() -> AgentSpec:
    """Создать AgentSpec с обязательным outlook.read_calendar."""
    return AgentSpec(
        agent_id="agent-1",
        name="Calendar agent",
        description="Calendar agent",
        goal=AgentGoal(
            main_goal="Прочитать календарь",
            success_criteria=["Календарь прочитан"],
            forbidden_actions=["Не менять календарь"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name="outlook.read_calendar",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            )
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="read_calendar",
                node_type=AgentGraphNodeType.TOOL_CALL,
                title="Прочитать календарь",
                description="Получить события Outlook",
                tool_name="outlook.read_calendar",
                next_on_success="final",
                next_on_error="final_failed",
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Финал",
                description="Финал",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final_failed",
                node_type=AgentGraphNodeType.FINAL,
                title="Ошибка",
                description="Ошибка",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
        ],
        runtime_limits=AgentRuntimeLimits(),
    )

