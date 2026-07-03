"""LLM-планировщик одного шага цикла агента (возвращает решение, не исполняет)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from agent_desktop_constructor.app.llm.agent_loop_prompts import build_agent_loop_prompt
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.models import LLMRequest
from agent_desktop_constructor.app.llm.supervisor_models import SupervisorDecision
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState
from agent_desktop_constructor.tools.catalog import ToolsCatalog


class LLMAgentLoopPlanner:
    """Спрашивает LLM, какой следующий шаг сделать в цикле выполнения."""

    def __init__(
        self,
        llm_client: OpenAICompatibleLLMClient,
        tools_catalog: ToolsCatalog,
    ) -> None:
        """Сохранить LLM client и каталог инструментов."""
        self._llm_client = llm_client
        self._tools_catalog = tools_catalog

    def decide(
        self,
        agent_spec: AgentSpec,
        runtime_state: AgentRuntimeState,
        executed_signatures: list[str] | None = None,
        repeat_notes: list[str] | None = None,
    ) -> SupervisorDecision:
        """Получить валидированное решение следующего шага."""
        messages = build_agent_loop_prompt(
            agent_spec=agent_spec,
            runtime_state=runtime_state,
            tools_catalog=self._tools_catalog,
            executed_signatures=executed_signatures or [],
            repeat_notes=repeat_notes or [],
        )
        response = self._llm_client.complete(
            LLMRequest(
                messages=messages,
                temperature=self._llm_client.config.temperature,
                model_name=self._llm_client.config.model_name,
                response_format="json_object",
            )
        )
        decision = _parse_agent_loop_decision(response.content)
        if decision.tool_call is not None:
            self._tools_catalog.validate_tool_names([decision.tool_call.tool_name])
        return decision


def _parse_agent_loop_decision(content: str) -> SupervisorDecision:
    """Распарсить JSON решения цикла в SupervisorDecision."""
    try:
        payload = _loads_json_object(content)
    except json.JSONDecodeError as exc:
        raise LLMInvalidJSONError(
            f"LLM вернул невалидный JSON решения цикла: {exc.msg}"
        ) from exc

    try:
        return SupervisorDecision.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidJSONError(
            f"JSON решения цикла не соответствует схеме SupervisorDecision: {exc}"
        ) from exc


def _loads_json_object(content: str) -> dict:
    """Распарсить JSON-объект, устойчиво к тексту вокруг и лишним префиксам.

    Сначала пробуем обычный json.loads. Если модель добавила пояснения до/после
    объекта, извлекаем первый сбалансированный {...} и парсим его.
    """
    text = content.strip()
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
