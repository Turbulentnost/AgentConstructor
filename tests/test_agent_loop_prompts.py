"""Тесты prompt-а LLM agent loop."""

from agent_desktop_constructor.app.llm.agent_loop_prompts import build_agent_loop_prompt
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def test_agent_loop_prompt_contains_temporal_context() -> None:
    """ReAct loop prompt содержит текущую дату и границы недели."""
    agent_spec = AgentBuilder().build_from_request("Найди совещания на этой неделе")
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "Найди совещания на этой неделе"},
    )

    messages = build_agent_loop_prompt(
        agent_spec=agent_spec,
        runtime_state=state,
        tools_catalog=load_tools_catalog(),
        executed_signatures=[],
        repeat_notes=[],
    )
    prompt_text = "\n".join(message.content for message in messages)

    assert '"temporal_context"' in prompt_text
    assert '"current_date"' in prompt_text
    assert '"current_week_start"' in prompt_text
    assert "YYYY-MM-DD" in prompt_text
    assert '"input_schema"' in prompt_text
    assert "outlook.read_calendar" in prompt_text
