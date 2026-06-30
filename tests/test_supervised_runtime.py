"""Тесты SupervisedAgentRuntime."""

from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.app.runtime.supervised_runtime import SupervisedAgentRuntime
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.report_tools import register_report_tools


class FakeSupervisor:
    """Mock LLM Supervisor, возвращающий последовательность решений."""

    def __init__(self, *decisions: SupervisorDecision) -> None:
        self.decisions = list(decisions)
        self.calls = 0
        self.latest_tool_names: list[str] = []

    def decide(self, agent_spec, runtime_state, latest_event, latest_tool_result):
        """Зафиксировать вызов и вернуть решение."""
        self.calls += 1
        assert latest_tool_result is not None
        self.latest_tool_names.append(latest_tool_result.tool_name)
        if self.decisions:
            return self.decisions.pop(0)
        return SupervisorDecision(
            decision_type=SupervisorDecisionType.CONTINUE_TO_NEXT,
            reason="Продолжить",
        )


def make_runtime(supervisor) -> SupervisedAgentRuntime:
    """Создать supervised runtime с fake registry."""
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    register_report_tools(registry, skip_existing=True)
    return SupervisedAgentRuntime(
        ToolGateway(registry),
        supervisor,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )


def test_supervised_runtime_calls_supervisor_after_tool_result() -> None:
    """SupervisedRuntime вызывает supervisor после tool_result."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CONTINUE_TO_NEXT,
            reason="Продолжить",
        )
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди совещания и распланируй график")

    state = runtime.run(agent_spec, {"user_request": "Найди совещания"})

    assert state.status == AgentRunStatus.COMPLETED
    assert supervisor.calls >= 1


def test_supervised_runtime_executes_tool_call_from_supervisor() -> None:
    """Runtime исполняет предложенный supervisor tool_call и снова спрашивает LLM."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Нужен отчёт",
            tool_call={
                "tool_name": "report.build_task_report",
                "input_data": {},
                "reason": "Сформировать черновой отчёт",
            },
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Отчёт готов",
            final_message="Готово",
        ),
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди поручения")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.COMPLETED
    assert "report.build_task_report" in [item.tool_name for item in state.tool_results]
    assert supervisor.latest_tool_names[-1] == "report.build_task_report"


def test_supervised_runtime_does_not_execute_unknown_tool() -> None:
    """Runtime не исполняет unknown tool, предложенный LLM."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Нужен неизвестный tool",
            tool_call={
                "tool_name": "invented.tool",
                "input_data": {},
                "reason": "bad",
            },
        )
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди поручения")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.FAILED
    assert "invented.tool" not in [item.tool_name for item in state.tool_results]
    assert any("ToolsCatalog" in error for error in state.errors)


def test_supervised_runtime_applies_finish_success() -> None:
    """SupervisedRuntime применяет finish_success."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Достаточно данных",
            final_message="Готово",
        )
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди поручения и отправь по почте")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.COMPLETED
    assert state.variables["final_message"] == "Готово"


def test_supervised_runtime_does_not_bypass_tool_gateway_for_dangerous() -> None:
    """Dangerous tool не выполняется без ToolGateway/HumanApproval."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Попробовать отправку",
            tool_call={
                "tool_name": "email.send",
                "input_data": {},
                "reason": "dangerous check",
            },
        )
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди поручения и отправь по почте")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert state.pending_human_approval.tool_name == "email.send"


def test_supervised_runtime_applies_ask_human() -> None:
    """Если supervisor вернул ask_human, Runtime ставит paused_for_human."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.ASK_HUMAN,
            reason="Нужно уточнение",
            human_question="Какой период анализировать?",
            human_options=["Сегодня", "Неделя"],
        )
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди поручения")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert state.pending_human_approval.question == "Какой период анализировать?"


def test_supervised_runtime_applies_request_credentials() -> None:
    """Если supervisor вернул request_credentials, Runtime ставит paused_for_credentials."""
    supervisor = FakeSupervisor(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.REQUEST_CREDENTIALS,
            reason="Нужна авторизация 1С вне LLM-контекста",
        )
    )
    runtime = make_runtime(supervisor)
    agent_spec = AgentBuilder().build_from_request("Найди поручения")

    state = runtime.run(agent_spec, {"user_request": "Найди поручения"})

    assert state.status == AgentRunStatus.PAUSED_FOR_CREDENTIALS
    assert "авторизация" in state.variables["credential_request_reason"].casefold()

