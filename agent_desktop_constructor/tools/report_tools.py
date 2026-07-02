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
        calendar_output = _calendar_output(input_data)
        if calendar_output is None:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_DATA_MISSING",
                error_message="Нет данных календаря для формирования рекомендаций",
            )
        if calendar_output.get("ok") is False or calendar_output.get("error_type"):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_DATA_NOT_AVAILABLE",
                error_message=(
                    calendar_output.get("error_message")
                    or calendar_output.get("error_type")
                    or "Данные календаря недоступны"
                ),
            )
        if "events" not in calendar_output:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_EVENTS_MISSING",
                error_message="Данные календаря не содержат events",
            )

        raw_events = calendar_output.get("events")
        if not isinstance(raw_events, list):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="CALENDAR_EVENTS_MISSING",
                error_message="Поле events должно быть списком",
            )
        events = [event for event in raw_events if isinstance(event, dict)]
        if not events:
            return ToolCallResult(
                ok=True,
                tool_name=self.definition.name,
                output_data={
                    "recommendation_text": "В выбранном периоде совещания не найдены.",
                    "meeting_count": 0,
                    "busy_slots": [],
                    "free_slots": [],
                    "risks": [],
                    "recommendations": [
                        "Используйте свободное время для фокус-работы или планирования."
                    ],
                },
            )

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
        free_slots: list[dict] = []
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
                "meeting_count": len(events),
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
    output = _calendar_output(input_data) or {}
    events = output.get("events", [])
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]
    return []


def _calendar_output(input_data: dict) -> dict | None:
    """Достать output outlook.read_calendar без подстановки fake данных."""
    tool_outputs = input_data.get("tool_outputs", {})
    if not isinstance(tool_outputs, dict):
        return None
    output = tool_outputs.get("outlook.read_calendar")
    if isinstance(output, dict):
        return output
    return None

