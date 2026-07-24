"""LLM-планировщик одного шага цикла агента (возвращает решение, не исполняет)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from agent_desktop_constructor.app.llm.agent_loop_prompts import build_agent_loop_prompt
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.models import LLMRequest
from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
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
        decision = _parse_agent_loop_decision(response.content, self._tools_catalog)
        _require_thought(decision)
        if decision.tool_call is not None:
            self._tools_catalog.validate_tool_names([decision.tool_call.tool_name])
        return decision


def _require_thought(decision: SupervisorDecision) -> None:
    """Обязать LLM пройти этап THINK перед действием (иначе повтор через runtime)."""
    thought = decision.thought
    if thought is None or not (thought.understanding or "").strip():
        raise LLMInvalidJSONError(
            "Пропущен обязательный этап THINK: сначала верни поле thought с "
            "непустым understanding (что понял), а также missing_info (чего не "
            "хватает), planned_actions (что планируешь), chosen_tool и why (какой "
            "инструмент нужен сейчас и почему). Только ПОСЛЕ этого выбирай "
            "decision_type."
        )
    if decision.decision_type in {
        SupervisorDecisionType.CALL_TOOL,
        SupervisorDecisionType.CALL_ADDITIONAL_TOOL,
        SupervisorDecisionType.RETRY_TOOL,
    }:
        actions = [a.strip() for a in (thought.planned_actions or []) if a and str(a).strip()]
        if not actions:
            raise LLMInvalidJSONError(
                "Для call_tool в thought.planned_actions нужен хотя бы один шаг плана."
            )
        if not (thought.why or "").strip():
            raise LLMInvalidJSONError(
                "Для call_tool поле thought.why обязательно (почему этот инструмент сейчас)."
            )


_VALID_DECISION_TYPES = {member.value for member in SupervisorDecisionType}
_TOOL_INPUT_KEYS = (
    "input_data",
    "input",
    "arguments",
    "parameters",
    "params",
    "tool_input",
)


def _parse_agent_loop_decision(
    content: str,
    tools_catalog: ToolsCatalog | None = None,
) -> SupervisorDecision:
    """Распарсить JSON решения цикла в SupervisorDecision."""
    try:
        payload = _loads_json_object(content)
    except json.JSONDecodeError as exc:
        raise LLMInvalidJSONError(
            f"LLM вернул невалидный JSON решения цикла: {exc.msg}"
        ) from exc

    payload = _normalize_decision_payload(payload, tools_catalog)

    try:
        return SupervisorDecision.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidJSONError(
            f"JSON решения цикла не соответствует схеме SupervisorDecision: {exc}"
        ) from exc


def _looks_like_tool_name(name: str, tools_catalog: ToolsCatalog | None) -> bool:
    """Понять, является ли строка именем инструмента (а не типом решения)."""
    if "." in name:
        return True
    if tools_catalog is None:
        return False
    try:
        tools_catalog.get_tool(name)
        return True
    except Exception:
        return False


def _extract_tool_input(payload: dict) -> dict:
    """Собрать входные данные инструмента из распространённых ключей LLM."""
    for key in _TOOL_INPUT_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    tool_call = payload.get("tool_call")
    if isinstance(tool_call, dict) and isinstance(tool_call.get("input_data"), dict):
        return tool_call["input_data"]
    return {}


def _normalize_decision_payload(
    payload: object,
    tools_catalog: ToolsCatalog | None,
) -> object:
    """Починить частые ошибки формата решения LLM без хардкодинга под задачу.

    Основные случаи:
    - LLM положила имя инструмента в decision_type вместо call_tool;
    - LLM указала tool_name на верхнем уровне без вложенного tool_call.
    """
    if not isinstance(payload, dict):
        return payload
    payload = dict(payload)
    payload = _normalize_thought(payload)
    decision_type = payload.get("decision_type")

    if (
        isinstance(decision_type, str)
        and decision_type not in _VALID_DECISION_TYPES
        and _looks_like_tool_name(decision_type, tools_catalog)
    ):
        tool_call = payload.get("tool_call")
        if not isinstance(tool_call, dict) or not tool_call.get("tool_name"):
            payload["tool_call"] = {
                "tool_name": decision_type,
                "input_data": _extract_tool_input(payload),
                "reason": (payload.get("reason") or f"Вызвать {decision_type}"),
            }
        payload["decision_type"] = SupervisorDecisionType.CALL_TOOL.value
        return payload

    if decision_type in {
        SupervisorDecisionType.CALL_TOOL.value,
        SupervisorDecisionType.CALL_ADDITIONAL_TOOL.value,
    } and not isinstance(payload.get("tool_call"), dict):
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and tool_name.strip():
            payload["tool_call"] = {
                "tool_name": tool_name,
                "input_data": _extract_tool_input(payload),
                "reason": (payload.get("reason") or f"Вызвать {tool_name}"),
            }

    return payload


_THOUGHT_KEYS = ("thought", "thinking", "think", "analysis", "reasoning")
_THOUGHT_FIELD_ALIASES = {
    "understanding": "understanding",
    "understood": "understanding",
    "what_i_understood": "understanding",
    "summary": "understanding",
    "missing_info": "missing_info",
    "missing": "missing_info",
    "what_is_missing": "missing_info",
    "gaps": "missing_info",
    "planned_actions": "planned_actions",
    "plan": "planned_actions",
    "actions": "planned_actions",
    "next_steps": "planned_actions",
    "chosen_tool": "chosen_tool",
    "tool": "chosen_tool",
    "next_tool": "chosen_tool",
    "why": "why",
    "reason": "why",
    "rationale": "why",
}


def _normalize_thought(payload: dict) -> dict:
    """Привести блок THINK к полям AgentThought, устойчиво к синонимам LLM."""
    raw = None
    for key in _THOUGHT_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            raw = value
            break
        if isinstance(value, str) and value.strip() and "thought" not in payload:
            raw = {"understanding": value}
            break
    if raw is None:
        return payload
    normalized: dict = {}
    for key, value in raw.items():
        field = _THOUGHT_FIELD_ALIASES.get(str(key).strip().casefold())
        if field is None:
            continue
        if field == "planned_actions":
            if isinstance(value, str):
                normalized[field] = [value] if value.strip() else []
            elif isinstance(value, list):
                normalized[field] = [str(item) for item in value if str(item).strip()]
        elif field == "chosen_tool":
            normalized[field] = str(value).strip() or None if value is not None else None
        else:
            normalized[field] = str(value)
    payload["thought"] = normalized
    return payload


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
