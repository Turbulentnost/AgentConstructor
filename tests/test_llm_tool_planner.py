"""Тесты LLMToolPlanner без реального HTTP."""

import pytest

from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.app.llm.tool_planner import LLMToolPlanner
from agent_desktop_constructor.core.models.llm_config import LLMConfig
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class FakeLLMClient:
    """Fake LLM client, возвращающий AgentPlan JSON."""

    def __init__(self, content: str) -> None:
        self.config = LLMConfig()
        self.content = content
        self.complete_called = False
        self.last_request: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Вернуть fake LLM response."""
        self.complete_called = True
        self.last_request = request
        return LLMResponse(content=self.content, raw={"fake": True})


def valid_agent_plan_json(tool_name: str = "outlook.read_calendar") -> str:
    """Вернуть валидный JSON LLMAgentPlan."""
    return f"""
    {{
      "agent_name": "Агент планирования графика",
      "goal": "Проанализировать календарь",
      "selected_tools": [
        {{
          "tool_name": "{tool_name}",
          "reason": "Нужно прочитать календарь",
          "required": true
        }}
      ],
      "steps": [
        {{
          "step_id": "read_calendar",
          "step_type": "tool_call",
          "title": "Прочитать календарь",
          "description": "Получить встречи Outlook",
          "tool_name": "{tool_name}",
          "depends_on": []
        }}
      ],
      "missing_data": [],
      "needs_human": false,
      "warnings": []
    }}
    """


def test_llm_tool_planner_accepts_fake_llm_json() -> None:
    """LLMToolPlanner принимает JSON от fake LLM."""
    client = FakeLLMClient(valid_agent_plan_json())
    planner = LLMToolPlanner(client)

    plan = planner.plan("Проверь календарь", load_tools_catalog())

    assert client.complete_called is True
    assert plan.agent_name == "Агент планирования графика"


def test_llm_tool_planner_valid_when_calendar_tool_selected() -> None:
    """Если fake LLM выбрала outlook.read_calendar, план валиден."""
    planner = LLMToolPlanner(FakeLLMClient(valid_agent_plan_json()))

    plan = planner.plan("Проверь календарь", load_tools_catalog())

    assert plan.selected_tools[0].tool_name == "outlook.read_calendar"


def test_llm_tool_planner_rejects_invented_tool() -> None:
    """Если fake LLM выбрала invented.tool, план падает."""
    planner = LLMToolPlanner(FakeLLMClient(valid_agent_plan_json("invented.tool")))

    with pytest.raises(ValueError, match="invented.tool"):
        planner.plan("Проверь календарь", load_tools_catalog())


def test_llm_tool_planner_prompt_forbids_direct_execution() -> None:
    """Prompt запрещает прямой вызов инструментов."""
    client = FakeLLMClient(valid_agent_plan_json())
    planner = LLMToolPlanner(client)

    planner.plan("Проверь календарь", load_tools_catalog())

    assert client.last_request is not None
    prompt_text = "\n".join(message.content for message in client.last_request.messages)
    assert "Ты не вызываешь инструменты напрямую" in prompt_text
    assert "Нельзя придумывать tool_name" in prompt_text
    assert "ToolGateway" in prompt_text


def test_llm_tool_planner_prompt_contains_temporal_context() -> None:
    """AgentPlan prompt содержит текущую дату для относительных дат."""
    client = FakeLLMClient(valid_agent_plan_json())
    planner = LLMToolPlanner(client)

    planner.plan("Проверь календарь на этой неделе", load_tools_catalog())

    assert client.last_request is not None
    prompt_text = "\n".join(message.content for message in client.last_request.messages)
    assert "Текущая дата выполнения:" in prompt_text
    assert "Текущая неделя:" in prompt_text
    assert "YYYY-MM-DD" in prompt_text

