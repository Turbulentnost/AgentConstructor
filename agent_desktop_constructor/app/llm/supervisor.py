"""LLM Supervisor, принимающий решения после событий Runtime."""

from __future__ import annotations

import json

from pydantic import ValidationError

from agent_desktop_constructor.app.core.models.run_events import AgentRunEvent
from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.models import LLMRequest
from agent_desktop_constructor.app.llm.supervisor_models import SupervisorDecision
from agent_desktop_constructor.app.llm.supervisor_prompts import build_supervisor_prompt
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRuntimeState,
    ToolCallRecord,
)
from agent_desktop_constructor.tools.catalog import ToolsCatalog


class LLMSupervisor:
    """LLM-контроллер выполнения, не исполняющий инструменты напрямую."""

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
        latest_event: AgentRunEvent | None,
        latest_tool_result: ToolCallRecord | None,
    ) -> SupervisorDecision:
        """Получить валидированное решение SupervisorDecision."""
        tools_context = self._tools_catalog.to_planner_context()
        messages = build_supervisor_prompt(
            agent_spec=agent_spec,
            runtime_state=runtime_state,
            latest_event=latest_event,
            latest_tool_result=latest_tool_result,
            tools_context=tools_context,
        )
        response = self._llm_client.complete(
            LLMRequest(
                messages=messages,
                temperature=self._llm_client.config.temperature,
                model_name=self._llm_client.config.model_name,
                response_format="json_object",
            )
        )
        decision = _parse_supervisor_decision(response.content)
        if decision.tool_call is not None:
            self._tools_catalog.validate_tool_names([decision.tool_call.tool_name])
        return decision


def _parse_supervisor_decision(content: str) -> SupervisorDecision:
    """Распарсить JSON SupervisorDecision."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMInvalidJSONError(
            f"LLM Supervisor вернул невалидный JSON: {exc.msg}"
        ) from exc

    try:
        return SupervisorDecision.model_validate(payload)
    except ValidationError as exc:
        raise LLMInvalidJSONError(
            f"JSON SupervisorDecision не соответствует схеме: {exc}"
        ) from exc

