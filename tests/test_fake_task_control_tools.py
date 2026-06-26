"""Тесты fake-инструментов агента контроля поручений."""

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.builder.graph_templates import build_task_control_graph
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeEmailCreateDraftTool,
    FakeEmailSendTool,
    FakeLLMAnalyzeCollectedDataTool,
    FakeLLMExtractStructuredFactsTool,
    FakeOneCGetTaskCardTool,
    FakeOneCSearchTasksTool,
    FakeOutlookReadCalendarTool,
    FakeOutlookReadTasksTool,
    FakeOutlookSearchMailTool,
    FakeReportBuildTaskReportTool,
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def make_agent_spec_for_email_send() -> AgentSpec:
    """Создать AgentSpec с разрешением на fake email.send."""
    return AgentSpec(
        agent_id="agent-1",
        name="Тестовый агент",
        description="Тестовый агент для fake email.send",
        goal=AgentGoal(
            main_goal="Проверить fake отправку",
            success_criteria=["Проверка завершена"],
            forbidden_actions=["Не отправлять без подтверждения"],
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
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Завершить",
                description="Финальный узел",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            )
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def make_all_fake_tools() -> list[BaseTool]:
    """Создать все fake tools контроля поручений."""
    return [
        FakeOutlookSearchMailTool(),
        FakeOutlookReadCalendarTool(),
        FakeOutlookReadTasksTool(),
        FakeOneCSearchTasksTool(),
        FakeOneCGetTaskCardTool(),
        FakeLLMExtractStructuredFactsTool(),
        FakeLLMAnalyzeCollectedDataTool(),
        FakeReportBuildTaskReportTool(),
        FakeEmailCreateDraftTool(),
        FakeEmailSendTool(),
    ]


def test_register_fake_task_control_tools_registers_all_tools() -> None:
    """register_fake_task_control_tools регистрирует все инструменты."""
    registry = ToolRegistry()

    register_fake_task_control_tools(registry)

    assert registry.list_tool_names() == {
        "outlook.search_mail",
        "outlook.read_calendar",
        "outlook.read_tasks",
        "onec.search_tasks",
        "onec.get_task_card",
        "llm.extract_structured_facts",
        "llm.analyze_collected_data",
        "report.build_task_report",
        "email.create_draft",
        "email.send",
    }


def test_all_fake_tools_inherit_from_base_tool() -> None:
    """Все fake tools наследуются от BaseTool."""
    for tool in make_all_fake_tools():
        assert isinstance(tool, BaseTool)


def test_fake_tool_names_match_task_control_builder_and_graph() -> None:
    """tool_name совпадают с AgentBuilder и graph_templates для task_control_agent."""
    fake_tool_names = {tool.definition.name for tool in make_all_fake_tools()}
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")
    builder_tool_names = {tool.tool_name for tool in agent_spec.tools}
    graph_tool_names = {
        node.tool_name
        for node in build_task_control_graph()
        if node.tool_name is not None
    }

    assert builder_tool_names.issubset(fake_tool_names)
    assert graph_tool_names.issubset(fake_tool_names)


def test_outlook_search_mail_returns_messages() -> None:
    """outlook.search_mail возвращает messages."""
    result = FakeOutlookSearchMailTool().execute({})

    assert isinstance(result, ToolCallResult)
    assert result.output_data is not None
    assert "messages" in result.output_data
    assert result.output_data["messages"][0]["id"] == "mail-1"


def test_outlook_read_calendar_returns_events() -> None:
    """outlook.read_calendar возвращает events."""
    result = FakeOutlookReadCalendarTool().execute({})

    assert result.output_data is not None
    assert "events" in result.output_data


def test_outlook_read_tasks_returns_tasks() -> None:
    """outlook.read_tasks возвращает tasks."""
    result = FakeOutlookReadTasksTool().execute({})

    assert result.output_data is not None
    assert "tasks" in result.output_data


def test_report_build_task_report_returns_report_text() -> None:
    """report.build_task_report возвращает report_text."""
    result = FakeReportBuildTaskReportTool().execute({})

    assert result.output_data is not None
    assert "report_text" in result.output_data


def test_email_create_draft_returns_draft_id() -> None:
    """email.create_draft возвращает draft_id."""
    result = FakeEmailCreateDraftTool().execute({})

    assert result.output_data is not None
    assert result.output_data["draft_id"] == "draft-1"


def test_email_send_has_dangerous_side_effect_level() -> None:
    """email.send имеет side_effect_level dangerous."""
    tool = FakeEmailSendTool()

    assert tool.definition.side_effect_level == ToolSideEffectLevel.DANGEROUS


def test_email_send_requires_human_approval() -> None:
    """email.send requires_human_approval=True."""
    tool = FakeEmailSendTool()

    assert tool.definition.requires_human_approval is True


def test_tool_gateway_blocks_email_send_without_human_approval() -> None:
    """Через ToolGateway email.send без human_approved не выполняется."""
    registry = ToolRegistry()
    registry.register(FakeEmailSendTool())
    gateway = ToolGateway(registry)

    result = gateway.execute_tool(
        agent_spec=make_agent_spec_for_email_send(),
        run_id="run-1",
        tool_name="email.send",
        input_data={},
        human_approved=False,
    )

    assert result.ok is False
    assert result.requires_human_approval is True
    assert result.error_type == "HUMAN_APPROVAL_REQUIRED"


def test_tool_gateway_executes_email_send_with_human_approval() -> None:
    """Через ToolGateway email.send с human_approved=True выполняется."""
    registry = ToolRegistry()
    registry.register(FakeEmailSendTool())
    gateway = ToolGateway(registry)

    result = gateway.execute_tool(
        agent_spec=make_agent_spec_for_email_send(),
        run_id="run-1",
        tool_name="email.send",
        input_data={},
        human_approved=True,
    )

    assert result.ok is True
    assert result.output_data == {"sent": True, "message_id": "sent-1"}


def test_all_fake_tools_return_tool_call_result() -> None:
    """Все fake tools возвращают ToolCallResult."""
    for tool in make_all_fake_tools():
        result = tool.execute({})
        assert isinstance(result, ToolCallResult)
        assert isinstance(result.output_data, dict)
