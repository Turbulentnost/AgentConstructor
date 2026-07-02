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


class LLMExtractStructuredFactsTool(BaseTool):
    """Извлекает структурированные факты (сущности, сроки, поручения) через LLM."""

    def __init__(self, llm_client: OpenAICompatibleLLMClient) -> None:
        """Создать LLM extract-facts tool."""
        super().__init__(
            ToolDefinition(
                name="llm.extract_structured_facts",
                title="Извлечение структурированных фактов",
                description=(
                    "Извлекает из собранных данных сущности, даты, документы, "
                    "ответственных, статусы, сроки и поручения."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LLM,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )
        self._llm_client = llm_client

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вызвать LLM и вернуть извлечённые факты."""
        source_text = input_data.get("text")
        payload = {
            "text": source_text,
            "fact_types": input_data.get("fact_types"),
            "collected_data": input_data.get("tool_outputs", {}),
            "user_request": input_data.get("user_request"),
        }
        try:
            response = self._llm_client.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "Ты извлекаешь структурированные факты из уже "
                                "собранных данных. Не вызывай инструменты и не "
                                "выполняй код. Верни JSON с полем facts (массив "
                                "объектов: entity, type, date, responsible, status, "
                                "due_date, source)."
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(payload, ensure_ascii=False),
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
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            parsed = {"facts": []}
        facts = parsed.get("facts", []) if isinstance(parsed, dict) else []
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"facts": facts, "raw_analysis": parsed},
        )


class LLMCompareSourcesTool(BaseTool):
    """Сравнивает информацию из разных источников (Outlook, 1С и т.д.) через LLM."""

    def __init__(self, llm_client: OpenAICompatibleLLMClient) -> None:
        """Создать LLM compare-sources tool."""
        super().__init__(
            ToolDefinition(
                name="llm.compare_sources",
                title="Сравнение источников",
                description=(
                    "Сравнивает информацию из Outlook, 1С, браузера, документов и "
                    "базы знаний, находит совпадения и расхождения."
                ),
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LLM,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )
        self._llm_client = llm_client

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вызвать LLM и вернуть совпадения/расхождения источников."""
        payload = {
            "sources": input_data.get("sources") or input_data.get("tool_outputs", {}),
            "comparison_goal": input_data.get("comparison_goal")
            or input_data.get("user_request"),
        }
        try:
            response = self._llm_client.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "Ты сравниваешь данные из разных источников. Не "
                                "вызывай инструменты и не выполняй код. Верни JSON "
                                "с полями matches (массив), conflicts (массив) и "
                                "summary (строка)."
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(payload, ensure_ascii=False),
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
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "matches": parsed.get("matches", []),
                "conflicts": parsed.get("conflicts", []),
                "summary": parsed.get("summary", "Сравнение источников выполнено."),
                "raw_analysis": parsed,
            },
        )


def register_llm_analysis_tools(
    registry: ToolRegistry,
    llm_client: OpenAICompatibleLLMClient,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать LLM analysis tools."""
    tools = [
        LLMAnalyzeCollectedDataTool(llm_client),
        LLMExtractStructuredFactsTool(llm_client),
        LLMCompareSourcesTool(llm_client),
    ]
    for tool in tools:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)

