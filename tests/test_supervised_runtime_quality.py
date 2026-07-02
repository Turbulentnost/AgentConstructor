"""Тесты quality evaluator в SupervisedAgentRuntime."""

from agent_desktop_constructor.app.llm.tool_result_quality import ToolResultQuality
from agent_desktop_constructor.app.runtime.supervised_runtime import SupervisedAgentRuntime
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.report_tools import register_report_tools


class ContinueSupervisor:
    """Supervisor, который не вмешивается в runtime."""

    def decide(self, agent_spec, runtime_state, latest_event, latest_tool_result):
        from agent_desktop_constructor.app.llm.supervisor_models import (
            SupervisorDecision,
            SupervisorDecisionType,
        )

        return SupervisorDecision(
            decision_type=SupervisorDecisionType.CONTINUE_TO_NEXT,
            reason="continue",
        )


class SuggestedToolEvaluator:
    """Quality evaluator, предлагающий следующий tool."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def evaluate(self, agent_spec, runtime_state, tool_result):
        """Вернуть suggested_tool_name."""
        return ToolResultQuality(
            is_useful=True,
            is_critical_failure=False,
            quality_score=0.5,
            reason="Нужен дополнительный tool",
            missing_information=[],
            suggested_next_action="call_tool",
            suggested_tool_name=self.tool_name,
            should_continue=True,
            should_finish=False,
            should_ask_human=False,
        )


def make_runtime(evaluator=None) -> SupervisedAgentRuntime:
    """Создать runtime с fake tools."""
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    register_report_tools(registry, skip_existing=True)
    return SupervisedAgentRuntime(
        ToolGateway(registry),
        ContinueSupervisor(),
        quality_evaluator=evaluator,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )


def test_quality_checks_are_saved_after_tool_result() -> None:
    """После каждого tool_result сохраняется state.variables['quality_checks']."""
    runtime = make_runtime()
    agent_spec = AgentBuilder().build_from_request("Найди совещания")

    state = runtime.run(agent_spec, {"user_request": "Найди совещания"})

    assert state.variables["quality_checks"]
    assert state.variables["quality_checks"][0]["tool_name"] == "outlook.read_calendar"


def test_unknown_suggested_tool_name_is_forbidden() -> None:
    """unknown suggested_tool_name запрещён."""
    runtime = make_runtime(SuggestedToolEvaluator("invented.tool"))
    agent_spec = AgentBuilder().build_from_request("Найди поручения")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.FAILED
    assert any("invented.tool" in error for error in state.errors)


def test_dangerous_suggested_tool_goes_to_human_approval() -> None:
    """dangerous suggested_tool_name уходит через ToolGateway/HumanApproval."""
    runtime = make_runtime(SuggestedToolEvaluator("email.send"))
    agent_spec = AgentBuilder().build_from_request("Найди поручения и отправь по почте")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert state.pending_human_approval.tool_name == "email.send"

