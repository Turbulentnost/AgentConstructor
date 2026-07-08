"""Тесты AgentContextManager, prompt integration и runtime snapshot."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.context.manager import AgentContextManager
from agent_desktop_constructor.app.context.models import (
    ContextBudget,
    ContextSection,
)
from agent_desktop_constructor.app.llm.agent_loop_prompts import build_agent_loop_prompt
from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.app.runtime.agent_loop_runtime import LLMAgentLoopRuntime
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


class OneToolPlanner:
    """Fake planner: один tool call, затем успешное завершение."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, agent_spec, runtime_state, executed_signatures=None, repeat_notes=None):
        self.calls += 1
        if self.calls == 1:
            return SupervisorDecision(
                decision_type=SupervisorDecisionType.CALL_TOOL,
                reason="Нужно получить данные",
                tool_call={
                    "tool_name": "outlook.read_calendar",
                    "input_data": {},
                    "reason": "прочитать календарь",
                },
            )
        return SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Данных достаточно",
            final_message="Готово",
        )


def _agent_spec():
    return AgentBuilder().build_from_request("Посмотри календарь Outlook")


def test_context_manager_records_sections_and_usage() -> None:
    """Manager пишет разделы, сжимает большие значения и считает проценты."""
    manager = AgentContextManager(
        ContextBudget(max_total_chars=1_000, max_entry_chars=120)
    )
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id="agent-1",
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "проверь календарь"},
    )

    snapshot = manager.update_state_context(state, agent_spec=_agent_spec())

    assert ContextSection.CREATION in snapshot.sections
    assert ContextSection.RUN in snapshot.sections
    assert snapshot.usage is not None
    assert snapshot.usage.total_chars <= manager.budget.max_total_chars
    assert state.variables["context_snapshot"]["usage"]["total_percent"] >= 0


def test_context_manager_restores_snapshot_from_state() -> None:
    """Snapshot восстанавливается из AgentRuntimeState.variables."""
    manager = AgentContextManager()
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id="agent-1",
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "проверь календарь"},
    )
    original = manager.update_state_context(state, agent_spec=_agent_spec())

    restored = manager.restore_from_state(state)

    assert restored.version == original.version
    assert restored.usage is not None
    assert restored.sections[ContextSection.CREATION]


def test_prompt_contains_agent_context_payload() -> None:
    """Prompt builder отдаёт LLM структурированный agent_context."""
    agent_spec = _agent_spec()
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "проверь календарь"},
    )

    messages = build_agent_loop_prompt(
        agent_spec,
        state,
        load_tools_catalog(),
        executed_signatures=[],
        repeat_notes=[],
    )
    payload_text = messages[1].content.split("\n", 1)[1]
    payload = json.loads(payload_text)

    assert "agent_context" in payload
    assert "creation" in payload["agent_context"]["sections"]
    assert state.variables["context_snapshot"]["usage"]["total_chars"] > 0


def test_runtime_persists_context_snapshot_after_tool_call() -> None:
    """LLM runtime обновляет context_snapshot после tool call и finish."""
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    runtime = LLMAgentLoopRuntime(
        tool_gateway=ToolGateway(registry),
        agent_loop_planner=OneToolPlanner(),
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )

    state = runtime.run(_agent_spec(), {"user_request": "проверь календарь"})

    assert state.status == AgentRunStatus.COMPLETED
    snapshot = state.variables["context_snapshot"]
    assert snapshot["usage"]["total_chars"] > 0
    assert snapshot["sections"]["tool_results"]
