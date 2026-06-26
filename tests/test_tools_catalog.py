"""Тесты каталога доступных инструментов."""

import json
from pathlib import Path

import pytest

from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.builder.graph_templates import (
    build_document_analysis_graph,
    build_generic_graph,
    build_meeting_agent_graph,
    build_task_control_graph,
)
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.catalog import (
    ToolsCatalog,
    validate_agent_spec_tools_against_catalog,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def test_load_tools_catalog_loads_default_json() -> None:
    """load_tools_catalog загружает default_tools_catalog.json."""
    catalog = load_tools_catalog()

    assert isinstance(catalog, ToolsCatalog)
    assert catalog.tools


def test_catalog_contains_outlook_search_mail() -> None:
    """Каталог содержит outlook.search_mail."""
    catalog = load_tools_catalog()

    assert catalog.has_tool("outlook.search_mail")


def test_catalog_contains_email_send() -> None:
    """Каталог содержит email.send."""
    catalog = load_tools_catalog()

    assert catalog.has_tool("email.send")


def test_catalog_contains_all_agent_builder_tools() -> None:
    """Все инструменты, которые использует AgentBuilder, есть в каталоге."""
    catalog = load_tools_catalog()
    agent_specs = [
        AgentBuilder().build_from_request("создай агента контроля поручений"),
        AgentBuilder().build_from_request("сделай протокол совещания"),
        AgentBuilder().build_from_request("проанализируй нормативный документ"),
        AgentBuilder().build_from_request("помоги структурировать информацию"),
    ]

    for agent_spec in agent_specs:
        catalog.validate_tool_names([tool.tool_name for tool in agent_spec.tools])


def test_catalog_contains_all_graph_template_tools() -> None:
    """Все инструменты, которые используются в graph_templates, есть в каталоге."""
    catalog = load_tools_catalog()
    graph_nodes = [
        *build_task_control_graph(),
        *build_meeting_agent_graph(),
        *build_document_analysis_graph(),
        *build_generic_graph(),
    ]
    tool_names = [
        node.tool_name for node in graph_nodes if node.tool_name is not None
    ]

    catalog.validate_tool_names(tool_names)


def test_email_send_is_dangerous_and_requires_approval() -> None:
    """email.send dangerous и requires_human_approval=True."""
    catalog = load_tools_catalog()
    tool = catalog.get_tool("email.send")

    assert tool.side_effect_level == ToolSideEffectLevel.DANGEROUS
    assert tool.requires_human_approval is True


def test_list_for_task_control_contains_outlook_search_mail() -> None:
    """list_for_agent_type('task_control_agent') содержит outlook.search_mail."""
    catalog = load_tools_catalog()
    tool_names = {tool.name for tool in catalog.list_for_agent_type("task_control_agent")}

    assert "outlook.search_mail" in tool_names


def test_list_for_document_analysis_contains_word_extract_text() -> None:
    """list_for_agent_type('document_analysis_agent') содержит word.extract_text."""
    catalog = load_tools_catalog()
    tool_names = {
        tool.name for tool in catalog.list_for_agent_type("document_analysis_agent")
    }

    assert "word.extract_text" in tool_names


def test_planner_context_contains_no_invented_tool_names_rule() -> None:
    """to_planner_context содержит правило 'Не придумывай новые tool_name'."""
    catalog = load_tools_catalog()

    context = catalog.to_planner_context("task_control_agent")

    assert "Не придумывай новые tool_name" in context
    assert "outlook.search_mail" in context


def test_get_unknown_tool_raises_error() -> None:
    """get_tool неизвестного инструмента вызывает ошибку."""
    catalog = load_tools_catalog()

    with pytest.raises(ValueError, match="unknown.tool"):
        catalog.get_tool("unknown.tool")


def test_validate_tool_names_unknown_tool_raises_error() -> None:
    """validate_tool_names с неизвестным tool_name вызывает ошибку."""
    catalog = load_tools_catalog()

    with pytest.raises(ValueError, match="invented.tool"):
        catalog.validate_tool_names(["outlook.search_mail", "invented.tool"])


def test_duplicate_tool_names_raise_error(tmp_path: Path) -> None:
    """Duplicate tool names в тестовом JSON вызывают ошибку."""
    source_catalog = load_tools_catalog()
    first_tool = source_catalog.tools[0].model_dump(mode="json")
    payload = {"tools": [first_tool, first_tool]}
    catalog_path = tmp_path / "duplicate-tools.json"
    catalog_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate tool names"):
        load_tools_catalog(catalog_path)


def test_validate_agent_spec_tools_against_catalog_accepts_valid_spec() -> None:
    """validate_agent_spec_tools_against_catalog пропускает валидный AgentSpec."""
    catalog = load_tools_catalog()
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    validate_agent_spec_tools_against_catalog(agent_spec, catalog)


def test_validate_agent_spec_tools_against_catalog_rejects_invented_tool() -> None:
    """validate_agent_spec_tools_against_catalog падает для invented.tool."""
    catalog = load_tools_catalog()
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")
    invalid_agent_spec = agent_spec.model_copy(
        update={
            "tools": [
                *agent_spec.tools,
                AgentToolPermission(
                    tool_name="invented.tool",
                    action_level=AgentActionLevel.READ,
                    requires_human_approval=False,
                    allowed=True,
                ),
            ],
            "graph_nodes": [
                *agent_spec.graph_nodes,
                AgentGraphNode(
                    node_id="invented",
                    node_type=AgentGraphNodeType.TOOL_CALL,
                    title="Выдуманный инструмент",
                    description="Узел с несуществующим инструментом.",
                    tool_name="invented.tool",
                    next_on_success="final",
                    next_on_error=None,
                    requires_human_approval=False,
                ),
            ],
        }
    )

    with pytest.raises(ValueError, match="invented.tool"):
        validate_agent_spec_tools_against_catalog(invalid_agent_spec, catalog)


def test_all_descriptions_and_planner_hints_are_not_empty() -> None:
    """Все description/planner_hint не пустые."""
    catalog = load_tools_catalog()

    assert all(tool.description.strip() for tool in catalog.tools)
    assert all(tool.planner_hint.strip() for tool in catalog.tools)


def test_all_dangerous_tools_require_approval() -> None:
    """Все dangerous tools требуют approval."""
    catalog = load_tools_catalog()

    assert all(
        tool.requires_human_approval
        for tool in catalog.tools
        if tool.side_effect_level == ToolSideEffectLevel.DANGEROUS
    )
