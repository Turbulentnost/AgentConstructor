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
        try:
            plan = _parse_agent_plan(response.content)
        except LLMInvalidJSONError as exc:
            # Частый сбой локальных/прокси LLM: на длинных browser-сценариях модель
            # начинает писать слишком подробный план и обрывает JSON внутри строки.
            # Второй проход просит короткий, исполняемый runtime-план.
            compact_response = self._llm_client.complete(
                LLMRequest(
                    messages=_build_compact_agent_plan_prompt(
                        normalized_request,
                        tools_catalog,
                        previous_error=str(exc),
                    ),
                    temperature=0.0,
                    model_name=self._llm_client.config.model_name,
                    response_format="json_object",
                    max_tokens=max(self._llm_client.config.max_tokens or 0, 12000),
                )
            )
            try:
                plan = _parse_agent_plan(compact_response.content)
            except LLMInvalidJSONError as retry_exc:
                raise LLMInvalidJSONError(
                    "LLM дважды вернула невалидный AgentPlan JSON. "
                    f"Первичная ошибка: {exc}. "
                    f"Ошибка compact retry: {retry_exc}"
                ) from retry_exc

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


def _build_compact_agent_plan_prompt(
    user_request: str,
    tools_catalog: ToolsCatalog,
    previous_error: str,
) -> list[LLMMessage]:
    """Собрать короткий retry-prompt, если первый AgentPlan JSON оборвался."""
    temporal_context = build_temporal_context_text()
    system_prompt = """
Ты — LLM Planner конструктора ИИ-агентов.
Предыдущий ответ был невалидным JSON, поэтому сейчас нужен КОМПАКТНЫЙ план.
Верни только один валидный JSON-объект LLMAgentPlan без Markdown и пояснений.
Не исполняй инструменты. Не придумывай tool_name. Runtime сам выполнит шаги.
""".strip()
    user_prompt = f"""
Задача пользователя:
{user_request}

Временной контекст:
{temporal_context}

Доступные инструменты:
{tools_catalog.to_planner_context()}

Предыдущая ошибка JSON:
{previous_error}

Верни строго JSON:
{{
  "agent_name": "до 40 символов",
  "goal": "одна короткая фраза до 180 символов",
  "selected_tools": [
    {{"tool_name": "точное имя из ToolsCatalog", "reason": "до 80 символов", "required": true}}
  ],
  "steps": [
    {{
      "step_id": "step_1",
      "step_type": "tool_call | analysis | human_review | final",
      "title": "до 50 символов",
      "description": "до 120 символов",
      "tool_name": null,
      "depends_on": []
    }}
  ],
  "missing_data": [],
  "needs_human": false,
  "warnings": [],
  "complexity": "low | medium | high"
}}

Жёсткие ограничения compact retry:
- Максимум 6 steps.
- Не копируй длинную инструкцию пользователя в title/description/goal.
- Для многошагового сайта выбери browser-набор инструментов и опиши действия
  короткими обобщёнными шагами, детали останутся в user_request для runtime.
- Если нужен код из Outlook/2FA/ручное действие, добавь human_review/ask-human шаг,
  но не запрашивай секреты в плане.
- Все строки должны быть короткими, без переводов строк внутри строк.
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

    payload = _normalize_agent_plan_payload(payload)
    try:
        return LLMAgentPlan.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidJSONError(
            f"JSON LLM не соответствует схеме LLMAgentPlan: {exc}"
        ) from exc


def _loads_json_object(content: str) -> dict:
    """Распарсить JSON-объект AgentPlan, игнорируя reasoning/prose вокруг."""
    text = (content or "").strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and _agent_plan_score(payload) > 0:
            return payload
    except json.JSONDecodeError:
        pass

    best_payload: dict | None = None
    best_score = -1
    for candidate in _extract_json_objects(text):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        score = _agent_plan_score(payload)
        if score > best_score:
            best_score = score
            best_payload = payload
        if score >= 4:
            break
    if best_payload is not None and best_score > 0:
        return best_payload

    # Сохраняем прежнее поведение/текст ошибки для полностью битого JSON.
    return json.loads(text)


def _agent_plan_score(payload: dict) -> int:
    """Оценить, похож ли объект на LLMAgentPlan."""
    normalized = _normalize_agent_plan_payload(payload)
    return sum(
        1
        for key in ("agent_name", "goal", "selected_tools", "steps")
        if key in normalized
    )


def _normalize_agent_plan_payload(payload: object) -> object:
    """Нормализовать частые варианты JSON-схемы, которые возвращают LLM.

    Это не подмена смысла плана: только приведение распространённых имён полей
    к нашей Pydantic-схеме.
    """
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    _rename_key(normalized, "name", "agent_name")
    _rename_key(normalized, "agentName", "agent_name")
    _rename_key(normalized, "tools", "selected_tools")
    _rename_key(normalized, "selectedTools", "selected_tools")
    _rename_key(normalized, "plan_steps", "steps")
    _rename_key(normalized, "actions", "steps")

    tools = normalized.get("selected_tools")
    if isinstance(tools, list):
        normalized["selected_tools"] = [
            _normalize_planned_tool(item) for item in tools
        ]

    steps = normalized.get("steps")
    if isinstance(steps, list):
        normalized["steps"] = [_normalize_planned_step(item) for item in steps]

    return normalized


def _normalize_planned_tool(value: object) -> object:
    """Нормализовать объект выбранного инструмента."""
    if not isinstance(value, dict):
        return value
    item = dict(value)
    _rename_key(item, "name", "tool_name")
    _rename_key(item, "tool", "tool_name")
    _rename_key(item, "toolName", "tool_name")
    if "reason" not in item and "description" in item:
        item["reason"] = item["description"]
    return item


def _normalize_planned_step(value: object) -> object:
    """Нормализовать объект шага плана."""
    if not isinstance(value, dict):
        return value
    item = dict(value)
    _rename_key(item, "id", "step_id")
    _rename_key(item, "type", "step_type")
    _rename_key(item, "stepType", "step_type")
    _rename_key(item, "tool", "tool_name")
    _rename_key(item, "toolName", "tool_name")
    _rename_key(item, "depends", "depends_on")
    _rename_key(item, "dependencies", "depends_on")
    if "description" not in item and "title" in item:
        item["description"] = item["title"]
    if "title" not in item and "description" in item:
        item["title"] = item["description"]
    return item


def _rename_key(payload: dict, old: str, new: str) -> None:
    """Переименовать ключ, если новый ещё не задан."""
    if new not in payload and old in payload:
        payload[new] = payload.pop(old)


def _extract_first_json_object(text: str) -> str | None:
    """Найти первый сбалансированный JSON-объект, игнорируя скобки в строках."""
    objects = _extract_json_objects(text)
    return objects[0] if objects else None


def _extract_json_objects(text: str) -> list[str]:
    """Найти сбалансированные JSON-объекты, игнорируя скобки в строках."""
    objects: list[str] = []
    for start in [index for index, char in enumerate(text) if char == "{"]:
        candidate = _extract_json_object_from(text, start)
        if candidate is not None:
            objects.append(candidate)
    return objects


def _extract_json_object_from(text: str, start: int) -> str | None:
    """Найти сбалансированный JSON-объект с конкретной позиции."""
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

