"""Тесты compact retry для LLM Tool Planner."""

from __future__ import annotations

from agent_desktop_constructor.app.llm.models import LLMRequest, LLMResponse
from agent_desktop_constructor.app.llm.tool_planner import LLMToolPlanner
from agent_desktop_constructor.core.models.llm_config import LLMConfig
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class SequenceLLMClient:
    """Fake LLM client, возвращающий ответы по очереди."""

    def __init__(self, responses: list[str]) -> None:
        """Сохранить ответы и историю запросов."""
        self.config = LLMConfig(max_tokens=4096)
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Вернуть следующий fake response."""
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("Неожиданный дополнительный LLM-вызов")
        return LLMResponse(content=self._responses.pop(0), raw={"fake": True})


def valid_agent_plan_json() -> str:
    """Вернуть компактный валидный LLMAgentPlan JSON."""
    return """
    {
      "agent_name": "Веб-подбор оборудования",
      "goal": "Подобрать оборудование на сайте и получить цену",
      "selected_tools": [
        {
          "tool_name": "browser.navigate",
          "reason": "Открыть сайт и начать сценарий",
          "required": true
        },
        {
          "tool_name": "browser.click",
          "reason": "Выбирать разделы и кнопки",
          "required": true
        }
      ],
      "steps": [
        {
          "step_id": "open_site",
          "step_type": "tool_call",
          "title": "Открыть сайт",
          "description": "Перейти на сайт подбора",
          "tool_name": "browser.navigate",
          "depends_on": []
        },
        {
          "step_id": "select_options",
          "step_type": "tool_call",
          "title": "Выбрать параметры",
          "description": "Кликать по разделам и заполнить форму",
          "tool_name": "browser.click",
          "depends_on": ["open_site"]
        },
        {
          "step_id": "finish",
          "step_type": "final",
          "title": "Завершить",
          "description": "Сообщить итог пользователю",
          "tool_name": null,
          "depends_on": ["select_options"]
        }
      ],
      "missing_data": [],
      "needs_human": false,
      "warnings": [],
      "complexity": "high"
    }
    """


def test_tool_planner_retries_with_compact_prompt_after_truncated_json() -> None:
    """Обрезанный AgentPlan JSON чинится повторным compact-запросом."""
    client = SequenceLLMClient(
        [
            '{"agent_name": "Длинный план", "goal": "оборванная строка',
            valid_agent_plan_json(),
        ]
    )
    planner = LLMToolPlanner(client)

    plan = planner.plan(
        "Зайди на сайт, заполни большую форму, получи код из Outlook и PDF",
        load_tools_catalog(),
    )

    assert plan.agent_name == "Веб-подбор оборудования"
    assert plan.complexity == "high"
    assert len(client.requests) == 2
    assert client.requests[0].max_tokens == 8000
    assert client.requests[1].max_tokens == 12000
    retry_prompt = "\n".join(message.content for message in client.requests[1].messages)
    assert "КОМПАКТНЫЙ план" in retry_prompt
    assert "Максимум 6 steps" in retry_prompt
