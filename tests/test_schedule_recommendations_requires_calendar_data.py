"""Тесты строгой зависимости schedule recommendations от календаря."""

from agent_desktop_constructor.tools.report_tools import (
    LocalBuildScheduleRecommendationsTool,
)


def test_missing_outlook_calendar_output_returns_error() -> None:
    """Нет outlook.read_calendar output => CALENDAR_DATA_MISSING."""
    result = LocalBuildScheduleRecommendationsTool().execute({"tool_outputs": {}})

    assert result.ok is False
    assert result.error_type == "CALENDAR_DATA_MISSING"


def test_failed_outlook_calendar_output_returns_error() -> None:
    """outlook.read_calendar failed => CALENDAR_DATA_NOT_AVAILABLE."""
    result = LocalBuildScheduleRecommendationsTool().execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "ok": False,
                    "error_type": "WORKER_TIMEOUT",
                    "error_message": "timed out",
                }
            }
        }
    )

    assert result.ok is False
    assert result.error_type == "CALENDAR_DATA_NOT_AVAILABLE"
    assert result.error_message == "timed out"


def test_empty_events_returns_successful_empty_recommendation() -> None:
    """events пустой список => ok=True, meeting_count=0."""
    result = LocalBuildScheduleRecommendationsTool().execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "events": [],
                    "count": 0,
                    "source": "fake_outlook",
                }
            }
        }
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["meeting_count"] == 0
    assert result.output_data["recommendation_text"] == (
        "В выбранном периоде совещания не найдены."
    )


def test_events_build_recommendations_from_input_events() -> None:
    """events есть => рекомендации строятся по этим events."""
    result = LocalBuildScheduleRecommendationsTool().execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "events": [
                        {
                            "id": "event-42",
                            "title": "Архитектурный комитет",
                            "start_at": "2026-06-30T12:00:00",
                        }
                    ],
                    "count": 1,
                    "source": "outlook_com",
                }
            }
        }
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["meeting_count"] == 1
    assert result.output_data["busy_slots"] == [
        {
            "title": "Архитектурный комитет",
            "start_at": "2026-06-30T12:00:00",
            "risk": "meeting_load",
        }
    ]


def test_output_does_not_include_meetings_absent_from_input() -> None:
    """В output не появляются встречи, которых не было во входных данных."""
    result = LocalBuildScheduleRecommendationsTool().execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "events": [
                        {
                            "title": "Единственная встреча",
                            "start_at": "2026-06-30T15:00:00",
                        }
                    ],
                    "count": 1,
                    "source": "outlook_com",
                }
            }
        }
    )

    assert result.ok is True
    assert result.output_data is not None
    serialized = str(result.output_data)
    assert "Единственная встреча" in serialized
    assert "Совещание по качеству" not in serialized


def test_missing_events_returns_calendar_events_missing() -> None:
    """events отсутствуют => CALENDAR_EVENTS_MISSING."""
    result = LocalBuildScheduleRecommendationsTool().execute(
        {
            "tool_outputs": {
                "outlook.read_calendar": {
                    "count": 1,
                    "source": "outlook_com",
                }
            }
        }
    )

    assert result.ok is False
    assert result.error_type == "CALENDAR_EVENTS_MISSING"

