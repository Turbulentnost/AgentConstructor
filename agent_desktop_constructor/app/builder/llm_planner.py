"""Безопасный LLM Planner для AgentBuilder."""

from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.models import (
    LLMPlanningResult,
    LLMRequest,
    parse_planning_result,
)
from agent_desktop_constructor.app.llm.prompts import build_tool_planner_prompt
from agent_desktop_constructor.tools.catalog import ToolsCatalog


class LLMPlanner:
    """LLM-помощник, который только планирует и не исполняет инструменты."""

    def __init__(
        self,
        llm_client: OpenAICompatibleLLMClient,
        tools_catalog: ToolsCatalog,
    ) -> None:
        """Сохранить LLM client и каталог допустимых инструментов."""
        self._llm_client = llm_client
        self._tools_catalog = tools_catalog

    def plan(
        self,
        user_request: str,
        agent_type: str | None = None,
    ) -> LLMPlanningResult:
        """Получить валидированный LLMPlanningResult для запроса пользователя."""
        tools_context = self._tools_catalog.to_planner_context(agent_type)
        messages = build_tool_planner_prompt(user_request, tools_context)
        response = self._llm_client.complete(
            LLMRequest(
                messages=messages,
                temperature=self._llm_client.config.temperature,
                model_name=self._llm_client.config.model_name,
                response_format="json_object",
            )
        )
        planning_result = parse_planning_result(response.content)
        self._validate_selected_tools(planning_result)
        return planning_result

    def _validate_selected_tools(self, planning_result: LLMPlanningResult) -> None:
        """Проверить, что LLM не придумала tool_name вне ToolsCatalog."""
        tool_names = [item.tool_name for item in planning_result.selected_tools]
        self._tools_catalog.validate_tool_names(tool_names)

