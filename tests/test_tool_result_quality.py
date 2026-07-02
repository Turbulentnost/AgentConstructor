"""Тесты оценки качества ToolCallResult."""

from agent_desktop_constructor.app.llm.tool_result_quality import (
    ToolResultQualityEvaluator,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    ToolCallRecord,
)


def test_worker_timeout_for_required_calendar_is_critical_failure() -> None:
    """WORKER_TIMEOUT у outlook.read_calendar => critical failure."""
    agent_spec = AgentBuilder().build_from_request("Найди совещания")
    result = ToolCallRecord(
        tool_name="outlook.read_calendar",
        input_data={},
        ok=False,
        error_type="WORKER_TIMEOUT",
        error_message="timed out",
    )

    quality = ToolResultQualityEvaluator().evaluate(
        agent_spec,
        AgentRuntimeState(
            run_id="run-1",
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.RUNNING,
        ),
        result,
    )

    assert quality.is_useful is False
    assert quality.is_critical_failure is True
    assert quality.suggested_next_action == "ask_human_or_retry"


def test_empty_output_is_not_useful() -> None:
    """Пустой output => not useful."""
    agent_spec = AgentBuilder().build_from_request("Найди совещания")
    result = ToolCallRecord(
        tool_name="outlook.read_calendar",
        input_data={},
        ok=True,
        output_data={},
    )

    quality = ToolResultQualityEvaluator().evaluate(
        agent_spec,
        AgentRuntimeState(
            run_id="run-1",
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.RUNNING,
        ),
        result,
    )

    assert quality.is_useful is False


def test_calendar_events_are_useful() -> None:
    """events в output => useful."""
    agent_spec = AgentBuilder().build_from_request("Найди совещания")
    result = ToolCallRecord(
        tool_name="outlook.read_calendar",
        input_data={},
        ok=True,
        output_data={"events": [{"id": "event-1"}]},
    )

    quality = ToolResultQualityEvaluator().evaluate(
        agent_spec,
        AgentRuntimeState(
            run_id="run-1",
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.RUNNING,
        ),
        result,
    )

    assert quality.is_useful is True
    assert quality.should_continue is True

