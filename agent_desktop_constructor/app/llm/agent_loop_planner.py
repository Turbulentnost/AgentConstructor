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
        payload = json.loads(content)
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
