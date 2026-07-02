"""Оценка качества результата инструмента для supervised runtime."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRuntimeState,
    ToolCallRecord,
)


class ToolResultQuality(BaseModel):
    """Оценка полезности и критичности результата tool_call."""

    is_useful: bool
    is_critical_failure: bool
    quality_score: float = Field(ge=0, le=1)
    reason: str
    missing_information: list[str] = Field(default_factory=list)
    suggested_next_action: str
    suggested_tool_name: str | None = None
    should_continue: bool
    should_finish: bool
    should_ask_human: bool

    @field_validator("reason", "suggested_next_action")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить обязательные текстовые поля."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value


class ToolResultQualityEvaluator:
    """Оценивает результат инструмента без прямого исполнения tools."""

    def evaluate(
        self,
        agent_spec: AgentSpec,
        runtime_state: AgentRuntimeState,
        tool_result: ToolCallRecord,
    ) -> ToolResultQuality:
        """Вернуть quality assessment для последнего результата инструмента."""
        is_required = _is_required_for_goal(agent_spec, tool_result.tool_name)
        if not tool_result.ok:
            return ToolResultQuality(
                is_useful=False,
                is_critical_failure=is_required,
                quality_score=0.0,
                reason=tool_result.error_message
                or tool_result.error_type
                or "Инструмент завершился ошибкой",
                missing_information=[tool_result.tool_name],
                suggested_next_action=(
                    "ask_human_or_retry"
                    if tool_result.error_type == "WORKER_TIMEOUT"
                    else "ask_human"
                ),
                should_continue=not is_required,
                should_finish=False,
                should_ask_human=is_required,
            )

        if not tool_result.output_data:
            return ToolResultQuality(
                is_useful=False,
                is_critical_failure=is_required,
                quality_score=0.0,
                reason="Инструмент не вернул output_data",
                missing_information=[tool_result.tool_name],
                suggested_next_action="ask_human_or_retry",
                should_continue=not is_required,
                should_finish=False,
                should_ask_human=is_required,
            )

        if tool_result.tool_name == "outlook.read_calendar":
            events = tool_result.output_data.get("events")
            useful = isinstance(events, list)
            return ToolResultQuality(
                is_useful=useful,
                is_critical_failure=not useful and is_required,
                quality_score=0.9 if useful else 0.0,
                reason=(
                    "Календарь содержит events"
                    if useful
                    else "Календарный результат не содержит events"
                ),
                missing_information=[] if useful else ["events"],
                suggested_next_action="continue" if useful else "ask_human_or_retry",
                should_continue=useful,
                should_finish=False,
                should_ask_human=not useful and is_required,
            )

        return ToolResultQuality(
            is_useful=True,
            is_critical_failure=False,
            quality_score=0.7,
            reason="Инструмент вернул непустой output_data",
            missing_information=[],
            suggested_next_action="continue",
            should_continue=True,
            should_finish=False,
            should_ask_human=False,
        )


def _is_required_for_goal(agent_spec: AgentSpec, tool_name: str) -> bool:
    """Определить обязательность tool по основному графу агента."""
    for node in agent_spec.graph_nodes:
        if node.tool_name == tool_name and node.next_on_error == "final_failed":
            return True
    return False

