"""Тесты meeting schedule agent."""

from agent_desktop_constructor.builder.agent_builder import AgentBuilder


SCHEDULE_REQUEST = (
    "Нужен агент, который смотрит все совещания в Outlook и выводит "
    "как лучше распланировать свой график"
)


def test_schedule_request_adds_llm_analysis_tool() -> None:
    """Запрос про планирование графика добавляет llm.analyze_collected_data."""
    agent_spec = AgentBuilder().build_from_request(SCHEDULE_REQUEST)

    tool_names = {tool.tool_name for tool in agent_spec.tools}

    assert "outlook.read_calendar" in tool_names
    assert "llm.analyze_collected_data" in tool_names


def test_schedule_request_adds_schedule_recommendations_tool() -> None:
    """Запрос про планирование графика добавляет report.build_schedule_recommendations."""
    agent_spec = AgentBuilder().build_from_request(SCHEDULE_REQUEST)

    tool_names = {tool.tool_name for tool in agent_spec.tools}
    node_tool_names = {node.tool_name for node in agent_spec.graph_nodes}

    assert "report.build_schedule_recommendations" in tool_names
    assert "report.build_schedule_recommendations" in node_tool_names


def test_schedule_agent_graph_order() -> None:
    """Граф содержит read_calendar -> analyze_calendar_load -> recommendations."""
    agent_spec = AgentBuilder().build_from_request(SCHEDULE_REQUEST)
    node_ids = [node.node_id for node in agent_spec.graph_nodes]

    assert node_ids[:4] == [
        "validate_request",
        "read_calendar",
        "analyze_calendar_load",
        "build_schedule_recommendations",
    ]

