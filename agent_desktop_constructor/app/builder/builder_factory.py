"""Фабрика AgentBuilder с опциональным LLM Planner."""

from pathlib import Path

from agent_desktop_constructor.app.builder.llm_planner import LLMPlanner
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.builder.data_requirements import DataRequirementAnalyzer
from agent_desktop_constructor.builder.template_selector import TemplateSelector
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def build_agent_builder(config: AppConfig) -> AgentBuilder:
    """Собрать AgentBuilder без вызова LLM и инструментов."""
    catalog_path = Path(config.tools_catalog_path) if config.tools_catalog_path else None
    tools_catalog = load_tools_catalog(catalog_path)
    template_selector = TemplateSelector()
    data_requirement_analyzer = DataRequirementAnalyzer()

    if config.use_llm_planner:
        llm_client = OpenAICompatibleLLMClient(config.to_llm_config())
        llm_planner = LLMPlanner(llm_client, tools_catalog)
        return AgentBuilder(
            template_selector=template_selector,
            data_requirement_analyzer=data_requirement_analyzer,
            tools_catalog=tools_catalog,
            llm_planner=llm_planner,
            use_llm_planner=True,
        )

    return AgentBuilder(
        template_selector=template_selector,
        data_requirement_analyzer=data_requirement_analyzer,
        tools_catalog=tools_catalog,
    )

