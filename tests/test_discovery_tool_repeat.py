"""Повтор excel.list_files после ответа человека / как discovery-инструмент."""

from __future__ import annotations

from agent_desktop_constructor.app.runtime.agent_loop_runtime import (
    DISCOVERY_REPEATABLE_TOOLS,
    _clear_discovery_signatures,
)
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)


def test_excel_list_files_is_discovery_repeatable() -> None:
    assert "excel.list_files" in DISCOVERY_REPEATABLE_TOOLS


def test_clear_discovery_signatures_keeps_other_tools() -> None:
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id="agent-1",
        status=AgentRunStatus.PAUSED_FOR_HUMAN,
        current_node_id=None,
        step_counter=2,
        variables={
            "loop_executed_signatures": [
                'excel.list_files::{"llm_reason": "x"}',
                'excel.read_workbook::{"filename": "a.xlsx"}',
            ]
        },
    )
    _clear_discovery_signatures(state)
    signatures = state.variables["loop_executed_signatures"]
    assert signatures == ['excel.read_workbook::{"filename": "a.xlsx"}']
