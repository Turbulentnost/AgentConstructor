"""End-to-end тесты MVP агента контроля поручений без Outlook и COM."""

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
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeEmailSendTool,
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def make_gateway_with_fake_task_tools() -> ToolGateway:
    """Создать ToolGateway с fake-инструментами контроля поручений."""
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    return ToolGateway(registry)


def get_tool_result_names(state) -> list[str]:
    """Вернуть имена инструментов из состояния запуска."""
    return [result.tool_name for result in state.tool_results]


def make_email_send_agent_spec() -> AgentSpec:
    """Создать минимальный AgentSpec с dangerous email.send."""
    return AgentSpec(
        agent_id="agent-email-send",
        name="Тестовый агент отправки",
        description="Минимальный агент для проверки HumanApproval email.send.",
        goal=AgentGoal(
            main_goal="Проверить отправку письма через HumanApproval",
            success_criteria=["Письмо обработано безопасно"],
            forbidden_actions=["Не отправлять письмо без подтверждения"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name="email.send",
                action_level=AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
                allowed=True,
            )
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="validate_request",
                node_type=AgentGraphNodeType.VALIDATION,
                title="Проверить запрос",
                description="Проверяет запрос перед отправкой письма.",
                tool_name=None,
                next_on_success="send_email",
                next_on_error=None,
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="send_email",
                node_type=AgentGraphNodeType.TOOL_CALL,
                title="Отправить письмо",
                description="Имитирует отправку письма после подтверждения.",
                tool_name="email.send",
                next_on_success="final",
                next_on_error=None,
                requires_human_approval=True,
            ),
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Завершить",
                description="Финальный узел успешного завершения.",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def test_task_control_agent_builds_report_without_sending_email() -> None:
    """Агент контроля поручений формирует отчёт без отправки письма."""
    agent_spec = AgentBuilder().build_from_request(
        "Создай агента, который проверяет Outlook и находит поручения"
    )
    gateway = make_gateway_with_fake_task_tools()
    runtime = SimpleAgentRuntime(gateway)

    state = runtime.run(agent_spec, run_id="run-e2e-1")

    assert agent_spec.name == "Агент контроля поручений"
    assert state.status == AgentRunStatus.COMPLETED
    assert {
        "outlook.search_mail",
        "outlook.read_calendar",
        "outlook.read_tasks",
        "report.build_task_report",
    }.issubset(set(get_tool_result_names(state)))
    report_output = state.variables["tool_outputs"]["report.build_task_report"]
    assert "report_text" in report_output
    assert not any("критичес" in error.casefold() for error in state.errors)
    assert "email.send" not in get_tool_result_names(state)


def test_send_intent_enables_dangerous_email_send_in_agent_spec() -> None:
    """Если пользователь просит отправить отчёт, email.send разрешён, но требует подтверждения."""
    agent_spec = AgentBuilder().build_from_request(
        "Создай агента, который проверяет Outlook, находит поручения и отправляет отчёт руководителю"
    )
    tools = {tool.tool_name: tool for tool in agent_spec.tools}

    assert "email.send" in tools
    assert tools["email.send"].allowed is True
    assert tools["email.send"].action_level == AgentActionLevel.DANGEROUS
    assert tools["email.send"].requires_human_approval is True


def test_dangerous_email_send_graph_pauses_and_resumes_after_approval() -> None:
    """Отдельный граф с dangerous tool останавливается и затем продолжается после approval."""
    registry = ToolRegistry()
    email_tool = FakeEmailSendTool()
    registry.register(email_tool)
    runtime = SimpleAgentRuntime(ToolGateway(registry))
    agent_spec = make_email_send_agent_spec()

    state = runtime.run(agent_spec, run_id="run-e2e-send")

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert not any(
        result.tool_name == "email.send" and result.ok
        for result in state.tool_results
    )

    resumed_state = runtime.resume(agent_spec, state, approved=True)

    assert resumed_state.status == AgentRunStatus.COMPLETED
    successful_send_results = [
        result
        for result in resumed_state.tool_results
        if result.tool_name == "email.send" and result.ok
    ]
    assert len(successful_send_results) == 1


def test_rejected_human_approval_does_not_send_email() -> None:
    """Отказ человека отменяет dangerous действие без успешного email.send."""
    registry = ToolRegistry()
    registry.register(FakeEmailSendTool())
    runtime = SimpleAgentRuntime(ToolGateway(registry))
    agent_spec = make_email_send_agent_spec()
    state = runtime.run(agent_spec, run_id="run-e2e-reject")

    resumed_state = runtime.resume(
        agent_spec,
        state,
        approved=False,
        comment="Не отправлять",
    )

    assert resumed_state.status in {AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}
    assert not any(
        result.tool_name == "email.send" and result.ok
        for result in resumed_state.tool_results
    )
    assert resumed_state.variables["human_decisions"][0]["selected_option"] == "Отклонить"


def test_e2e_uses_fake_tools_without_outlook_or_com() -> None:
    """E2E сценарий использует fake tools и не требует Outlook/COM."""
    gateway = make_gateway_with_fake_task_tools()

    assert gateway is not None
