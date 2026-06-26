"""Тесты AgentBuilder с расширенными инструментами."""

from agent_desktop_constructor.builder.agent_builder import AgentBuilder


def tool_names(agent_spec) -> set[str]:
    """Вернуть имена tools AgentSpec."""
    return {tool.tool_name for tool in agent_spec.tools}


def test_task_control_agent_contains_onec_tasks() -> None:
    """task_control_agent содержит onec.search_tasks."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert "onec.search_tasks" in tool_names(agent_spec)
    assert "llm.analyze_collected_data" in tool_names(agent_spec)


def test_document_analysis_agent_contains_browser_and_onec_tools() -> None:
    """document_analysis_agent содержит browser и 1C tools."""
    agent_spec = AgentBuilder().build_from_request("проанализируй нормативный документ")
    names = tool_names(agent_spec)

    assert "browser.search_web" in names
    assert "onec.search_documents" in names
    assert "llm.analyze_collected_data" in names


def test_generic_agent_contains_browser_and_llm_analysis() -> None:
    """generic_agent содержит browser и LLM analytics tools."""
    agent_spec = AgentBuilder().build_from_request("помоги найти и обобщить информацию")
    names = tool_names(agent_spec)

    assert "browser.search_web" in names
    assert "browser.open_page" in names
    assert "llm.generate_text" in names
    assert "llm.analyze_collected_data" in names


def test_agent_builder_does_not_create_unknown_tool_names() -> None:
    """AgentBuilder не создаёт tool_name, которого нет в ToolsCatalog."""
    builder = AgentBuilder()

    for request in [
        "создай агента контроля поручений",
        "проанализируй нормативный документ",
        "помоги найти и обобщить информацию",
    ]:
        agent_spec = builder.build_from_request(request)
        known = builder.tools_catalog.list_tool_names()
        graph_tools = {
            node.tool_name for node in agent_spec.graph_nodes if node.tool_name
        }
        assert tool_names(agent_spec).issubset(known)
        assert graph_tools.issubset(known)

