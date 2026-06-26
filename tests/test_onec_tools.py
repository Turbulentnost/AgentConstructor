"""Тесты 1С read-only tools."""

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.onec_tools import (
    OneCGetDocumentCardTool,
    OneCGetTaskCardTool,
    OneCSearchDocumentsTool,
    OneCSearchTasksTool,
    register_onec_readonly_tools,
)
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.onec_worker import OneCReadOnlyWorker


def make_onec_agent_spec() -> AgentSpec:
    """Создать AgentSpec с 1С tools."""
    return AgentSpec(
        agent_id="agent-1",
        name="1C test agent",
        description="Тестовый агент 1С",
        goal=AgentGoal(
            main_goal="Проверить 1С read-only tools",
            success_criteria=["Данные прочитаны"],
            forbidden_actions=["Не изменять 1С"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name="onec.search_documents",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            )
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Финал",
                description="Финал",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            )
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def test_all_onec_tools_are_read_only() -> None:
    """Все onec tools имеют side_effect_level=read."""
    worker = OneCReadOnlyWorker()
    tools = [
        OneCSearchDocumentsTool(worker),
        OneCGetDocumentCardTool(worker),
        OneCSearchTasksTool(worker),
        OneCGetTaskCardTool(worker),
    ]

    for tool in tools:
        assert tool.definition.side_effect_level == ToolSideEffectLevel.READ
        assert tool.definition.requires_human_approval is False


def test_register_onec_readonly_tools() -> None:
    """register_onec_readonly_tools регистрирует все 1С tools."""
    registry = ToolRegistry()

    register_onec_readonly_tools(registry, OneCReadOnlyWorker())

    assert registry.list_tool_names() == {
        "onec.search_documents",
        "onec.get_document_card",
        "onec.search_tasks",
        "onec.get_task_card",
    }


def test_tool_gateway_calls_onec_tool() -> None:
    """ToolGateway вызывает onec tools."""
    registry = ToolRegistry()
    register_onec_readonly_tools(registry, OneCReadOnlyWorker())
    gateway = ToolGateway(registry)

    result = gateway.execute_tool(
        agent_spec=make_onec_agent_spec(),
        run_id="run-1",
        tool_name="onec.search_documents",
        input_data={"query": "служебная"},
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["source"] == "onec_readonly"

