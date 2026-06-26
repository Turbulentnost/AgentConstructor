"""Тесты конструктора AgentSpec."""

from uuid import UUID

import pytest

from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.builder.graph_templates import validate_graph_template
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGraphNodeType,
    AgentSpec,
)
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.catalog import ToolsCatalog
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def get_tool_map(agent_spec: AgentSpec):
    """Вернуть разрешения инструментов по имени."""
    return {tool.tool_name: tool for tool in agent_spec.tools}


def build_catalog_without(tool_name: str) -> ToolsCatalog:
    """Вернуть тестовый каталог без указанного инструмента."""
    catalog = load_tools_catalog()
    return ToolsCatalog(
        tools=[tool for tool in catalog.tools if tool.name != tool_name]
    )


def test_agent_builder_uses_default_tools_catalog() -> None:
    """AgentBuilder по умолчанию загружает ToolsCatalog."""
    builder = AgentBuilder()

    assert isinstance(builder.tools_catalog, ToolsCatalog)
    assert builder.tools_catalog.has_tool("outlook.search_mail")


def test_build_from_request_returns_agent_spec_for_task_control() -> None:
    """build_from_request для запроса контроля поручений возвращает AgentSpec."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert isinstance(agent_spec, AgentSpec)


def test_task_control_agent_has_expected_name() -> None:
    """AgentSpec.name == 'Агент контроля поручений'."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert agent_spec.name == "Агент контроля поручений"


def test_agent_spec_contains_graph_nodes() -> None:
    """AgentSpec содержит graph_nodes."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert agent_spec.graph_nodes


def test_agent_spec_contains_data_requirements() -> None:
    """AgentSpec содержит data_requirements."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert agent_spec.data_requirements


def test_agent_spec_contains_outlook_search_mail_tool() -> None:
    """AgentSpec содержит tool outlook.search_mail."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert "outlook.search_mail" in get_tool_map(agent_spec)


def test_agent_spec_tools_exist_in_catalog() -> None:
    """Все tools в AgentSpec есть в ToolsCatalog."""
    builder = AgentBuilder()
    agent_spec = builder.build_from_request("создай агента контроля поручений")

    for tool in agent_spec.tools:
        assert builder.tools_catalog.has_tool(tool.tool_name)


def test_task_control_fails_when_catalog_misses_outlook_search_mail() -> None:
    """Если в каталоге нет outlook.search_mail, task_control_agent не создаётся."""
    builder = AgentBuilder(
        tools_catalog=build_catalog_without("outlook.search_mail")
    )

    with pytest.raises(ValueError, match="outlook.search_mail"):
        builder.build_from_request("создай агента контроля поручений")


def test_agent_spec_contains_report_build_task_report_tool() -> None:
    """AgentSpec содержит tool report.build_task_report."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert "report.build_task_report" in get_tool_map(agent_spec)


def test_email_send_has_dangerous_action_level() -> None:
    """email.send имеет action_level dangerous."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert get_tool_map(agent_spec)["email.send"].action_level == AgentActionLevel.DANGEROUS


def test_email_send_requires_human_approval() -> None:
    """email.send requires_human_approval=True."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert get_tool_map(agent_spec)["email.send"].requires_human_approval is True


def test_agent_spec_action_level_matches_catalog_side_effect_level() -> None:
    """action_level инструмента соответствует side_effect_level из каталога."""
    builder = AgentBuilder()
    agent_spec = builder.build_from_request("создай агента контроля поручений")

    for tool_permission in agent_spec.tools:
        catalog_tool = builder.tools_catalog.get_tool(tool_permission.tool_name)
        assert tool_permission.action_level == AgentActionLevel(
            catalog_tool.side_effect_level.value
        )


def test_email_send_gets_dangerous_from_catalog() -> None:
    """email.send получает dangerous из ToolsCatalog."""
    builder = AgentBuilder()
    agent_spec = builder.build_from_request("создай агента контроля поручений")
    catalog_tool = builder.tools_catalog.get_tool("email.send")

    assert catalog_tool.side_effect_level == ToolSideEffectLevel.DANGEROUS
    assert get_tool_map(agent_spec)["email.send"].action_level == AgentActionLevel(
        catalog_tool.side_effect_level.value
    )


def test_email_send_gets_human_approval_from_catalog() -> None:
    """email.send получает requires_human_approval=True из ToolsCatalog."""
    builder = AgentBuilder()
    agent_spec = builder.build_from_request("создай агента контроля поручений")
    catalog_tool = builder.tools_catalog.get_tool("email.send")

    assert catalog_tool.requires_human_approval is True
    assert (
        get_tool_map(agent_spec)["email.send"].requires_human_approval
        == catalog_tool.requires_human_approval
    )


def test_email_send_disabled_without_send_intent() -> None:
    """Если нет намерения отправки, email.send allowed=False."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert get_tool_map(agent_spec)["email.send"].allowed is False


def test_email_send_enabled_with_send_intent() -> None:
    """Если есть 'отправь отчёт руководителю', email.send allowed=True."""
    agent_spec = AgentBuilder().build_from_request(
        "создай агента контроля поручений и отправь отчёт руководителю"
    )

    assert get_tool_map(agent_spec)["email.send"].allowed is True


def test_meeting_request_selects_meeting_agent_name() -> None:
    """Для meeting-запроса выбирается 'Агент по совещаниям'."""
    agent_spec = AgentBuilder().build_from_request("сделай протокол совещания")

    assert agent_spec.name == "Агент по совещаниям"


def test_document_request_selects_document_analysis_agent_name() -> None:
    """Для document-запроса выбирается 'Агент анализа документов'."""
    agent_spec = AgentBuilder().build_from_request(
        "проанализируй нормативный документ"
    )

    assert agent_spec.name == "Агент анализа документов"


def test_neutral_request_selects_generic_agent_name() -> None:
    """Для нейтрального запроса выбирается 'Универсальный агент'."""
    agent_spec = AgentBuilder().build_from_request("помоги структурировать информацию")

    assert agent_spec.name == "Универсальный агент"


def test_empty_request_raises_value_error() -> None:
    """Пустой запрос вызывает ValueError."""
    with pytest.raises(ValueError, match="user_request"):
        AgentBuilder().build_from_request("   ")


def test_agent_spec_graph_nodes_pass_template_validation() -> None:
    """Все graph_nodes AgentSpec проходят валидацию."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    validate_graph_template(agent_spec.graph_nodes)


def test_all_graph_tool_names_are_declared_in_tools() -> None:
    """Все tool_name в graph_nodes есть в tools."""
    agent_spec = AgentBuilder().build_from_request(
        "проанализируй нормативный документ"
    )
    tool_names = {tool.tool_name for tool in agent_spec.tools}

    for node in agent_spec.graph_nodes:
        if node.tool_name is not None:
            assert node.tool_name in tool_names


def test_builder_does_not_create_tool_name_missing_from_catalog() -> None:
    """Builder не создаёт tool_name, отсутствующий в каталоге."""
    builder = AgentBuilder(tools_catalog=load_tools_catalog())
    agent_spec = builder.build_from_request("сделай протокол совещания")
    catalog_tool_names = builder.tools_catalog.list_tool_names()

    assert all(tool.tool_name in catalog_tool_names for tool in agent_spec.tools)


def test_agent_spec_has_final_node() -> None:
    """В AgentSpec есть хотя бы один final-узел."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    assert any(
        node.node_type == AgentGraphNodeType.FINAL for node in agent_spec.graph_nodes
    )


def test_agent_id_is_non_empty_uuid() -> None:
    """AgentSpec.agent_id не пустой и выглядит как UUID."""
    agent_spec = AgentBuilder().build_from_request("создай агента контроля поручений")

    parsed_uuid = UUID(agent_spec.agent_id)
    assert str(parsed_uuid) == agent_spec.agent_id
