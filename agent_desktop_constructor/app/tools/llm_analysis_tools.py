"""LLM analysis tools для обработки уже собранных данных."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.llm.client import OpenAICompatibleLLMClient
from agent_desktop_constructor.app.llm.errors import LLMError
from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.registry import ToolRegistry


class LLMAnalyzeCollectedDataTool(BaseTool):
    """Анализирует собранные Runtime данные через LLM."""

    def __init__(self, llm_client: OpenAICompatibleLLMClient) -> None:
        """Создать LLM analysis tool."""
        super().__init__(
            ToolDefinition(
                name="llm.analyze_collected_data",
                title="Анализ собранных данных",
                description="Анализирует tool_outputs и формирует структурированные выводы.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LLM,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )
        self._llm_client = llm_client

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вызвать LLM и вернуть структурированный анализ."""
        try:
            response = self._llm_client.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "Ты анализируешь уже собранные данные агента. "
                                "Не вызывай инструменты, не выполняй код, верни JSON."
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "goal": input_data.get("agent_goal"),
                                    "collected_data": input_data.get("tool_outputs", {}),
                                    "user_request": input_data.get("user_request"),
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                    temperature=self._llm_client.config.temperature,
                    model_name=self._llm_client.config.model_name,
                    response_format="json_object",
                )
            )
        except LLMError as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="LLM_CONNECTION_ERROR",
                error_message=str(exc),
            )

        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError:
            payload = {"summary": response.content}
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "summary": payload.get("summary", "Данные проанализированы."),
                "findings": payload.get("findings", []),
                "risks": payload.get("risks", []),
                "recommendations": payload.get("recommendations", []),
                "confidence": payload.get("confidence", 0.7),
                "raw_analysis": payload,
            },
        )


def register_llm_analysis_tools(
    registry: ToolRegistry,
    llm_client: OpenAICompatibleLLMClient,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать LLM analysis tools."""
    tool = LLMAnalyzeCollectedDataTool(llm_client)
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)

