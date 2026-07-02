"""Тесты prompt-а LLM Supervisor."""

from agent_desktop_constructor.app.llm.supervisor_prompts import (
    build_supervisor_prompt,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def test_supervisor_prompt_forbids_direct_tool_access() -> None:
    """LLM Supervisor prompt запрещает прямой вызов инструментов."""
    agent_spec = AgentBuilder().build_from_request("Найди совещания")
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
    )

    messages = build_supervisor_prompt(
        agent_spec=agent_spec,
        runtime_state=state,
        latest_event=None,
        latest_tool_result=None,
        tools_context=load_tools_catalog().to_planner_context(),
    )
    prompt_text = "\n".join(message.content for message in messages)

    assert "Ты не вызываешь инструменты напрямую" in prompt_text
    assert "Ты не работаешь с COM напрямую" in prompt_text
    assert "Ты не можешь придумывать tool_name" in prompt_text
    assert "запись в 1С" in prompt_text
    assert "нажатие кнопок подтверждения в браузере" in prompt_text


def test_supervisor_prompt_contains_temporal_context() -> None:
    """Supervisor prompt содержит temporal_context."""
    agent_spec = AgentBuilder().build_from_request("Найди совещания")
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
    )

    messages = build_supervisor_prompt(
        agent_spec=agent_spec,
        runtime_state=state,
        latest_event=None,
        latest_tool_result=None,
        tools_context=load_tools_catalog().to_planner_context(),
    )
    prompt_text = "\n".join(message.content for message in messages)

    assert '"temporal_context"' in prompt_text
    assert '"current_date"' in prompt_text
    assert "YYYY-MM-DD" in prompt_text

