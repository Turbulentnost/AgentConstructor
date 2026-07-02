"""Тесты безопасного LLMPlanner без реального HTTP."""

import pytest

from agent_desktop_constructor.app.builder.llm_planner import LLMPlanner
from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.core.models.llm_config import LLMConfig
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class FakeLLMClient:
    """Fake LLM client, возвращающий заданный JSON."""

    def __init__(self, content: str) -> None:
        """Сохранить content и счётчики вызовов."""
        self.config = LLMConfig()
        self.content = content
        self.complete_called = False
        self.last_request: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Вернуть fake LLMResponse без HTTP."""
        self.complete_called = True
        self.last_request = request
        return LLMResponse(content=self.content, raw={"fake": True})


def valid_planning_json(tool_name: str = "outlook.search_mail") -> str:
    """Вернуть валидный JSON LLMPlanningResult."""
    return f"""
    {{
      "understood_goal": "Найти поручения в Outlook",
      "selected_tools": [
        {{
          "tool_name": "{tool_name}",
          "reason": "Нужно прочитать данные пользователя",
          "required": true
        }}
      ],
      "missing_data": [],
      "needs_human": false,
      "needs_human_reason": null,
      "needs_human_or_new_tool": false,
      "warnings": []
    }}
    """


def test_llm_planner_calls_client_complete() -> None:
    """LLMPlanner вызывает client.complete."""
    client = FakeLLMClient(valid_planning_json())
    planner = LLMPlanner(client, load_tools_catalog())

    planner.plan("Проверь Outlook", "task_control_agent")

    assert client.complete_called is True


def test_llm_planner_uses_tools_catalog_context() -> None:
    """LLMPlanner передаёт в prompt context из ToolsCatalog."""
    client = FakeLLMClient(valid_planning_json())
    planner = LLMPlanner(client, load_tools_catalog())

    planner.plan("Проверь Outlook", "task_control_agent")

    assert client.last_request is not None
    prompt_text = "\n".join(message.content for message in client.last_request.messages)
    assert "Доступные инструменты" in prompt_text
    assert "outlook.search_mail" in prompt_text
    assert "Не придумывай новые tool_name" in prompt_text
    assert "Входные параметры:" in prompt_text
    assert "folder" in prompt_text
    assert "date_from" in prompt_text


def test_llm_planner_parses_valid_json() -> None:
    """LLMPlanner парсит валидный JSON в LLMPlanningResult."""
    client = FakeLLMClient(valid_planning_json())
    planner = LLMPlanner(client, load_tools_catalog())

    result = planner.plan("Проверь Outlook", "task_control_agent")

    assert result.understood_goal == "Найти поручения в Outlook"
    assert result.selected_tools[0].tool_name == "outlook.search_mail"


def test_llm_planner_rejects_invented_tool_name() -> None:
    """LLMPlanner падает, если LLM вернула invented.tool."""
    client = FakeLLMClient(valid_planning_json("invented.tool"))
    planner = LLMPlanner(client, load_tools_catalog())

    with pytest.raises(ValueError, match="invented.tool"):
        planner.plan("Проверь Outlook", "task_control_agent")

