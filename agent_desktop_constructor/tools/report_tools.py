"""Локальные report tools без изменений внешних систем."""

from __future__ import annotations

from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.registry import ToolRegistry


class LocalBuildMeetingSummaryTool(BaseTool):
    """Формирует локальную сводку совещаний."""

    def __init__(self) -> None:
        """Создать tool."""
        super().__init__(
            ToolDefinition(
                name="report.build_meeting_summary",
                title="Формирование материалов совещания",
                description="Формирует сводку, повестку или протокол без записи в Outlook.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть краткую сводку по событиям календаря."""
        events = _calendar_events(input_data)
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "summary_text": f"Найдено совещаний: {len(events)}. Подготовлена краткая сводка.",
                "event_count": len(events),
            },
        )


class LocalBuildScheduleRecommendationsTool(BaseTool):
    """Формирует рекомендации по планированию графика на основе календаря."""

    def __init__(self) -> None:
        """Создать tool."""
        super().__init__(
            ToolDefinition(
                name="report.build_schedule_recommendations",
                title="Рекомендации по планированию графика",
                description="Формирует рекомендации по расписанию без изменения календаря.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Сформировать рекомендации по плотности, окнам и фокус-времени."""
        events = _calendar_events(input_data)
        analytics = (
            input_data.get("tool_outputs", {})
            .get("llm.analyze_collected_data", {})
        )
        busy_slots = [
            {
                "title": event.get("title", "Совещание"),
                "start_at": event.get("start_at"),
                "risk": "meeting_load",
            }
            for event in events
        ]
        free_slots = [
            {"start_at": "2026-06-26T09:00:00", "end_at": "2026-06-26T10:30:00"},
            {"start_at": "2026-06-26T15:30:00", "end_at": "2026-06-26T17:00:00"},
        ]
        risks = list(analytics.get("risks", [])) or [
            "Возможна высокая плотность встреч без фокус-времени."
        ]
        recommendations = [
            "Сгруппировать короткие встречи в один блок.",
            "Оставить минимум один 90-минутный слот для фокус-работы.",
            "Перенести необязательные встречи из перегруженных интервалов.",
        ]
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "recommendation_text": "\n".join(recommendations),
                "busy_slots": busy_slots,
                "free_slots": free_slots,
                "risks": risks,
                "recommendations": recommendations,
            },
        )


def register_report_tools(
    registry: ToolRegistry,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать локальные report tools."""
    for tool in [LocalBuildMeetingSummaryTool(), LocalBuildScheduleRecommendationsTool()]:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)


def _calendar_events(input_data: dict) -> list[dict]:
    """Достать events из tool_outputs outlook.read_calendar."""
    output = input_data.get("tool_outputs", {}).get("outlook.read_calendar", {})
    events = output.get("events", [])
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]
    return []

