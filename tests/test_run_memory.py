"""Тесты rolling memory agent-loop."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.llm.agent_loop_prompts import build_agent_loop_prompt
from agent_desktop_constructor.app.llm.run_memory import (
    DEFAULT_RECENT_STEPS,
    PROMPT_SOFT_LIMIT_CHARS,
    apply_memory_notes,
    build_executed_steps_for_prompt,
    compact_overflow_steps_into_memory,
    ensure_run_memory,
    shrink_payload_if_needed,
    update_run_memory_from_tool,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    ToolCallRecord,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


def _record(
    tool: str,
    *,
    ok: bool = True,
    output: dict | None = None,
    error: str | None = None,
) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=tool,
        input_data={},
        ok=ok,
        output_data=output or {},
        error_message=error,
        error_type="Error" if not ok else None,
    )


def test_executed_steps_window_keeps_only_recent() -> None:
    """В промпт уходит только окно последних N шагов."""
    results = [
        _record(f"tool.{i}", output={"i": i, "stdout_summary": f"ok-{i}"})
        for i in range(25)
    ]
    steps = build_executed_steps_for_prompt(results, recent_limit=DEFAULT_RECENT_STEPS)
    assert len(steps) == DEFAULT_RECENT_STEPS
    assert steps[0]["tool_name"] == "tool.15"
    assert steps[-1]["tool_name"] == "tool.24"


def test_update_run_memory_keeps_artifacts_and_facts() -> None:
    """Пути/листы из tool result попадают в pinned run_memory."""
    variables: dict = {}
    update_run_memory_from_tool(
        variables,
        _record(
            "excel.read_workbook",
            output={
                "path": r"C:\work\report.xlsx",
                "sheet_names": ["Spec", "Data"],
                "stdout_summary": "листы: Spec, Data",
            },
        ),
        step=3,
    )
    apply_memory_notes(variables, ["роль листа Spec = спецификация"])
    memory = ensure_run_memory(variables)

    paths = [item["path"] for item in memory["artifacts"]]
    assert r"C:\work\report.xlsx" in paths
    assert any("Spec" in fact for fact in memory["facts"])
    assert any("спецификация" in fact for fact in memory["facts"])


def test_failures_pinned_until_same_tool_succeeds() -> None:
    """Незакрытые ошибки остаются в last_failures."""
    variables: dict = {}
    update_run_memory_from_tool(
        variables,
        _record("code.run_python", ok=False, error="SyntaxError: bad"),
        step=1,
    )
    assert ensure_run_memory(variables)["last_failures"]
    update_run_memory_from_tool(
        variables,
        _record("code.run_python", output={"path": "code/main.py", "ok": True}),
        step=2,
    )
    assert ensure_run_memory(variables)["last_failures"] == []


def test_prompt_includes_run_memory_not_full_history() -> None:
    """build_agent_loop_prompt: recent window + run_memory, не все 20+ шагов."""
    agent_spec = AgentBuilder().build_from_request("Проанализируй Excel")
    state = AgentRuntimeState(
        run_id="run-mem",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "Проанализируй Excel"},
    )
    for i in range(18):
        record = _record(
            f"excel.step_{i}",
            output={
                "path": f"out_{i}.xlsx" if i % 5 == 0 else None,
                "stdout_summary": ("X" * 400) + f"-step-{i}",
            },
        )
        # Убрать None path
        if record.output_data.get("path") is None:
            record.output_data.pop("path", None)
        state.tool_results.append(record)
        update_run_memory_from_tool(state.variables, record, step=i + 1)
    compact_overflow_steps_into_memory(state)

    # Закрепим артефакт вручную, чтобы гарантировать наличие в payload
    apply_memory_notes(state.variables, ["важный факт про лист Spec"])
    memory = ensure_run_memory(state.variables)
    memory["artifacts"].append(
        {"path": "out_0.xlsx", "kind": "spreadsheet", "note": "first"}
    )

    messages = build_agent_loop_prompt(
        agent_spec=agent_spec,
        runtime_state=state,
        tools_catalog=load_tools_catalog(),
        executed_signatures=[],
        repeat_notes=[],
    )
    prompt_text = "\n".join(message.content for message in messages)
    # Вытащить JSON user_payload после преамбулы.
    user_content = messages[-1].content
    json_start = user_content.find("{")
    assert json_start >= 0
    payload = json.loads(user_content[json_start:])
    step_names = [s["tool_name"] for s in payload["executed_steps"]]

    assert "run_memory" in payload
    assert "важный факт про лист Spec" in prompt_text
    assert "out_0.xlsx" in prompt_text
    assert "workspace" in prompt_text.lower() or "диск" in prompt_text.lower()
    assert "excel.step_0" not in step_names
    assert "excel.step_17" in step_names
    assert len(step_names) <= DEFAULT_RECENT_STEPS
    assert "memory_notes" in prompt_text


def test_shrink_payload_tightens_window() -> None:
    """При превышении soft limit окно и summaries ужимаются."""
    huge_steps = [
        {
            "tool_name": f"t{i}",
            "ok": True,
            "output_summary": "Y" * 800,
        }
        for i in range(12)
    ]
    payload = {
        "executed_steps": huge_steps,
        "observation_history": [{"step": i} for i in range(12)],
        "collected_data": {
            f"tool_{i}": {"stdout_summary": "Z" * 500, "noise": "N" * 500}
            for i in range(20)
        },
        "pad": "P" * (PROMPT_SOFT_LIMIT_CHARS + 1000),
    }
    shrink_payload_if_needed(payload)
    budget = payload["_prompt_budget"]
    assert budget["tightened"] is True
    assert len(payload["executed_steps"]) <= 6
    assert all(
        len(step.get("output_summary") or "") <= 321
        for step in payload["executed_steps"]
    )
