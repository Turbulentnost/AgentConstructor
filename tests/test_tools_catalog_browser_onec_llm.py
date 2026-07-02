"""Тесты расширенного каталога browser/1C/LLM analytics tools."""

from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def test_catalog_contains_browser_tools() -> None:
    """В каталоге есть browser tools."""
    catalog = load_tools_catalog()

    assert catalog.has_tool("browser.search_web")
    assert catalog.has_tool("browser.open_page")
    assert catalog.has_tool("browser.extract_table")
    assert catalog.has_tool("browser.scroll_page")
    assert catalog.has_tool("browser.click_link")


def test_catalog_contains_onec_tools() -> None:
    """В каталоге есть 1C read-only tools."""
    catalog = load_tools_catalog()

    assert catalog.has_tool("onec.search_documents")
    assert catalog.has_tool("onec.get_document_card")
    assert catalog.has_tool("onec.search_tasks")
    assert catalog.has_tool("onec.get_task_card")


def test_catalog_contains_llm_analytics_tools() -> None:
    """В каталоге есть LLM analytics tools."""
    catalog = load_tools_catalog()

    assert catalog.has_tool("llm.analyze_collected_data")
    assert catalog.has_tool("llm.compare_sources")
    assert catalog.has_tool("llm.extract_structured_facts")


def test_onec_tools_are_read_only() -> None:
    """Все 1C tools имеют side_effect_level=read."""
    catalog = load_tools_catalog()

    for tool in catalog.tools:
        if tool.category == "onec":
            assert tool.side_effect_level == ToolSideEffectLevel.READ


def test_browser_tools_are_read_only() -> None:
    """Все browser tools имеют side_effect_level=read."""
    catalog = load_tools_catalog()

    for tool in catalog.tools:
        if tool.category == "browser":
            assert tool.side_effect_level == ToolSideEffectLevel.READ


def test_llm_analytics_tools_are_not_dangerous() -> None:
    """LLM analytics tools не dangerous."""
    catalog = load_tools_catalog()

    for tool in catalog.tools:
        if tool.category == "llm_analysis":
            assert tool.side_effect_level != ToolSideEffectLevel.DANGEROUS

