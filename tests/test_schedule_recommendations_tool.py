"""Тесты report.build_schedule_recommendations."""

from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.tools.report_tools import (
    LocalBuildScheduleRecommendationsTool,
)


def test_schedule_recommendations_tool_is_create_draft() -> None:
    """Tool формирует рекомендации без изменения календаря."""
    tool = LocalBuildScheduleRecommendationsTool()

    assert tool.definition.side_effect_level == ToolSideEffectLevel.CREATE_DRAFT
    assert tool.definition.requires_human_approval is False


def test_schedule_recommendations_tool_uses_calendar_and_analysis() -> None:
    """Tool возвращает busy/free slots и рекомендации."""
    tool = LocalBuildScheduleRecommendationsTool()

    result = tool.execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "events": [{"title": "Совещание", "start_at": "2026-06-26T11:00:00"}]
                },
                "llm.analyze_collected_data": {
                    "risks": ["Перегрузка утром"],
                    "recommendations": ["Освободить утренний слот"],
                },
            }
        }
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["busy_slots"]
    assert result.output_data["meeting_count"] == 1
    assert "Перегрузка утром" in result.output_data["risks"]
    assert result.output_data["recommendations"] == ["Освободить утренний слот"]


def test_schedule_recommendations_without_analysis_has_no_fabricated_text() -> None:
    """Без аналитики LLM инструмент не выдумывает рекомендации."""
    tool = LocalBuildScheduleRecommendationsTool()

    result = tool.execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "events": [{"title": "Совещание", "start_at": "2026-06-26T11:00:00"}]
                }
            }
        }
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["recommendations"] == []
    assert result.output_data["analysis_source"] == "none"

