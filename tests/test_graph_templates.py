"""Тесты шаблонов графов агентов."""

from agent_desktop_constructor.builder.graph_templates import (
    AgentTemplateName,
    build_document_analysis_graph,
    build_generic_graph,
    build_meeting_agent_graph,
    build_task_control_graph,
    get_graph_template,
    validate_graph_template,
)


def get_node_map(nodes):
    """Вернуть словарь узлов по node_id."""
    return {node.node_id: node for node in nodes}


def test_build_task_control_graph_returns_non_empty_list() -> None:
    """build_task_control_graph возвращает непустой список."""
    assert build_task_control_graph()


def test_task_control_graph_passes_validation() -> None:
    """task_control_graph проходит validate_graph_template."""
    validate_graph_template(build_task_control_graph())


def test_task_control_graph_contains_required_nodes() -> None:
    """В task_control_graph есть обязательные узлы."""
    nodes = get_node_map(build_task_control_graph())

    assert {
        "validate_request",
        "read_mail",
        "read_calendar",
        "read_tasks",
        "extract_task_candidates",
        "analyze_confidence",
        "human_review_if_needed",
        "build_report",
        "final",
    }.issubset(nodes)


def test_read_mail_uses_outlook_search_mail() -> None:
    """read_mail использует outlook.search_mail."""
    nodes = get_node_map(build_task_control_graph())

    assert nodes["read_mail"].tool_name == "outlook.search_mail"


def test_read_calendar_uses_outlook_read_calendar() -> None:
    """read_calendar использует outlook.read_calendar."""
    nodes = get_node_map(build_task_control_graph())

    assert nodes["read_calendar"].tool_name == "outlook.read_calendar"


def test_read_tasks_uses_outlook_read_tasks() -> None:
    """read_tasks использует outlook.read_tasks."""
    nodes = get_node_map(build_task_control_graph())

    assert nodes["read_tasks"].tool_name == "outlook.read_tasks"


def test_build_report_uses_report_build_task_report() -> None:
    """build_report использует report.build_task_report."""
    nodes = get_node_map(build_task_control_graph())

    assert nodes["build_report"].tool_name == "report.build_task_report"


def test_all_transitions_point_to_existing_node_ids() -> None:
    """Все переходы указывают на существующие node_id."""
    nodes = build_task_control_graph()
    node_ids = {node.node_id for node in nodes}

    for node in nodes:
        if node.next_on_success is not None:
            assert node.next_on_success in node_ids
        if node.next_on_error is not None:
            assert node.next_on_error in node_ids


def test_meeting_agent_passes_validation() -> None:
    """meeting_agent проходит validate_graph_template."""
    validate_graph_template(build_meeting_agent_graph())


def test_document_analysis_agent_passes_validation() -> None:
    """document_analysis_agent проходит validate_graph_template."""
    validate_graph_template(build_document_analysis_graph())


def test_generic_agent_passes_validation() -> None:
    """generic_agent проходит validate_graph_template."""
    validate_graph_template(build_generic_graph())


def test_unknown_template_returns_generic_graph() -> None:
    """get_graph_template для неизвестного имени возвращает generic_graph."""
    nodes = get_graph_template("unknown_template")

    assert [node.node_id for node in nodes] == [
        node.node_id for node in build_generic_graph()
    ]


def test_known_template_returns_task_control_graph() -> None:
    """get_graph_template возвращает выбранный известный шаблон."""
    nodes = get_graph_template(AgentTemplateName.TASK_CONTROL_AGENT.value)

    assert get_node_map(nodes)["read_mail"].tool_name == "outlook.search_mail"
