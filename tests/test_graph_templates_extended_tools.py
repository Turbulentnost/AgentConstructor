"""Тесты graph templates с 1C/browser/LLM analytics nodes."""

from agent_desktop_constructor.builder.graph_templates import (
    build_document_analysis_graph,
    build_task_control_graph,
    validate_graph_template,
)


def node_map(nodes):
    """Вернуть nodes по node_id."""
    return {node.node_id: node for node in nodes}


def test_task_control_graph_contains_onec_and_llm_nodes() -> None:
    """task_control_graph содержит 1C и LLM analytics nodes."""
    nodes = node_map(build_task_control_graph())

    assert nodes["read_onec_tasks"].tool_name == "onec.search_tasks"
    assert (
        nodes["analyze_collected_tasks"].tool_name == "llm.analyze_collected_data"
    )
    assert nodes["read_tasks"].next_on_success == "read_onec_tasks"
    assert nodes["extract_task_candidates"].next_on_success == "analyze_collected_tasks"


def test_document_analysis_graph_contains_onec_browser_and_llm_nodes() -> None:
    """document_analysis_graph содержит 1C/browser/LLM analytics nodes."""
    nodes = node_map(build_document_analysis_graph())

    assert nodes["search_onec_documents"].tool_name == "onec.search_documents"
    assert nodes["search_web_sources"].tool_name == "browser.search_web"
    assert nodes["llm_analyze_document"].tool_name == "llm.analyze_collected_data"
    assert nodes["search_related_documents"].next_on_success == "search_onec_documents"
    assert nodes["analyze_document"].next_on_success == "llm_analyze_document"


def test_extended_graphs_pass_validation() -> None:
    """Расширенные графы проходят структурную валидацию."""
    validate_graph_template(build_task_control_graph())
    validate_graph_template(build_document_analysis_graph())

