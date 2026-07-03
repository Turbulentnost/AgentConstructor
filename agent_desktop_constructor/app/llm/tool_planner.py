"""LLM Tool Planner, возвращающий AgentPlan без исполнения инструментов."""

from __future__ import annotations

import json

from pydantic import ValidationError

from agent_desktop_constructor.app.llm.agent_plan_models import LLMAgentPlan
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.app.llm.temporal_context import (
    build_temporal_context_text,
)
from agent_desktop_constructor.tools.catalog import ToolsCatalog


AGENT_PLAN_SCHEMA_DESCRIPTION = """
Верни только JSON-объект без Markdown:
{
  "agent_name": "краткое название агента",
  "goal": "цель агента",
  "selected_tools": [
    {"tool_name": "точное имя из ToolsCatalog", "reason": "почему нужен", "required": true}
  ],
  "steps": [
    {
      "step_id": "validate_request",
      "step_type": "validation | tool_call | analysis | routing | human_review | final",
      "title": "название шага",
      "description": "что делает шаг",
      "tool_name": null,
      "depends_on": []
    }
  ],
  "missing_data": [],
  "needs_human": false,
  "warnings": [],
  "complexity": "low | medium | high"
}
""".strip()


class LLMToolPlanner:
    """LLM-планировщик, выбирающий tools и шаги только из ToolsCatalog."""

    def __init__(self, llm_client: OpenAICompatibleLLMClient) -> None:
        """Сохранить LLM client."""
        self._llm_client = llm_client

    def plan(self, user_request: str, tools_catalog: ToolsCatalog) -> LLMAgentPlan:
        """Получить и провалидировать LLM AgentPlan."""
        normalized_request = user_request.strip()
        if not normalized_request:
            raise ValueError("user_request не должен быть пустым")

        # План может быть длинным (много инструментов и шагов). Даём planning
        # запросу заметно больший лимит токенов, чтобы JSON не обрывался.
        planning_max_tokens = max(self._llm_client.config.max_tokens or 0, 8000)
        response = self._llm_client.complete(
            LLMRequest(
                messages=_build_agent_plan_prompt(normalized_request, tools_catalog),
                temperature=self._llm_client.config.temperature,
                model_name=self._llm_client.config.model_name,
                response_format="json_object",
                max_tokens=planning_max_tokens,
            )
        )
        plan = _parse_agent_plan(response.content)
        tool_names = [tool.tool_name for tool in plan.selected_tools]
        tool_names.extend(
            step.tool_name for step in plan.steps if step.tool_name is not None
        )
        tools_catalog.validate_tool_names(tool_names)
        return plan


def _build_agent_plan_prompt(
    user_request: str,
    tools_catalog: ToolsCatalog,
) -> list[LLMMessage]:
    """Собрать prompt выбора tools и шагов AgentSpec."""
    temporal_context = build_temporal_context_text()
    system_prompt = """
Ты — LLM Planner конструктора ИИ-агентов.
Ты не вызываешь инструменты напрямую.
Ты не вызываешь ToolGateway.
Ты не работаешь с COM.
Ты не открываешь Outlook, 1С или браузер напрямую.
Ты не пишешь Python-код.
Ты только выбираешь tool_name из ToolsCatalog и строишь JSON-план.
Нельзя придумывать tool_name.
Если подходящего инструмента нет, заполни missing_data или warnings.
Runtime позже исполнит план через ToolGateway и HumanApproval.
Ответ верни только JSON по схеме LLMAgentPlan.
""".strip()
    user_prompt = f"""
Исходный запрос пользователя:
{user_request}

Временной контекст:
{temporal_context}

Контекст доступных инструментов:
{tools_catalog.to_planner_context()}

JSON-схема:
{AGENT_PLAN_SCHEMA_DESCRIPTION}

Правила:
- Используй только tool_name из ToolsCatalog.
- Не вызывай инструменты и не описывай выполнение как уже сделанное.
- Не отправляй письма, не меняй Outlook, не пиши в 1С, не выполняй код.
- Для относительных дат ("сегодня", "эта неделя", "на этой неделе") используй временной контекст выше.
- Если инструмент поддерживает date/date_from/date_to, передавай даты в формате YYYY-MM-DD.
- Если пользователь спрашивает про совещания, встречи, расписание, занятость или дела на день/неделю — включи outlook.read_calendar.
- Если пользователь спрашивает про дни рождения в Outlook-сообщениях — включи outlook.search_mail.
- Если нужен tool вне каталога, укажи warning/missing_data.
- Оцени сложность задачи в поле complexity:
  - "low" — 1 система, чтение/простое действие, мало шагов;
  - "medium" — несколько шагов или 2 системы, немного интерактива;
  - "high" — многошаговая автоматизация UI (клики, ввод в формы, коды, PDF),
    несколько систем (браузер + Outlook + Excel), длинные сценарии.
""".strip()
    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]


def _parse_agent_plan(content: str) -> LLMAgentPlan:
    """Распарсить JSON LLMAgentPlan, устойчиво к тексту вокруг объекта."""
    try:
        payload = _loads_json_object(content)
    except json.JSONDecodeError as exc:
        raise LLMInvalidJSONError(
            f"LLM вернула невалидный AgentPlan JSON: {exc.msg}"
        ) from exc

    try:
        return LLMAgentPlan.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidJSONError(
            f"JSON LLM не соответствует схеме LLMAgentPlan: {exc}"
        ) from exc


def _loads_json_object(content: str) -> dict:
    """Распарсить JSON-объект, игнорируя пояснения/текст вокруг него."""
    text = (content or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        candidate = _extract_first_json_object(text)
        if candidate is None:
            raise
        return json.loads(candidate)


def _extract_first_json_object(text: str) -> str | None:
    """Найти первый сбалансированный JSON-объект, игнорируя скобки в строках."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None

