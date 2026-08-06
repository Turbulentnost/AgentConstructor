"""Тесты сохранения трассировки THINK/decision/tool в файлы."""

from pathlib import Path

from agent_desktop_constructor.app.llm.supervisor_models import (
    AgentThought,
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.app.runtime.agent_loop_runtime import LLMAgentLoopRuntime
from agent_desktop_constructor.app.runtime.run_transcript import RunTranscriptLogger
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    ToolCallRecord,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.report_tools import register_report_tools


def test_transcript_logger_writes_md_jsonl_and_snapshot(tmp_path: Path) -> None:
    """Logger создаёт markdown/jsonl/json и дописывает события."""
    logger = RunTranscriptLogger(traces_root=tmp_path)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    state = AgentRuntimeState(
        run_id="run-trace-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "график"},
        step_counter=1,
    )
    decision = SupervisorDecision(
        decision_type=SupervisorDecisionType.CALL_TOOL,
        reason="Читаю календарь",
        thought=AgentThought(
            understanding="Нужны совещания",
            missing_info="нет данных календаря",
            planned_actions=["прочитать календарь"],
            chosen_tool="outlook.read_calendar",
            why="это источник встреч",
        ),
        tool_call={
            "tool_name": "outlook.read_calendar",
            "input_data": {},
            "reason": "данные",
        },
    )

    paths = logger.ensure_paths(agent_spec, state)
    logger.log_decision(agent_spec, state, decision)
    logger.log_tool_result(
        agent_spec,
        state,
        ToolCallRecord(
            tool_name="outlook.read_calendar",
            input_data={},
            output_data={"events": [{"title": "Standup"}], "screenshot_base64": "AAA"},
            ok=True,
        ),
    )
    logger.log_run_status(agent_spec, state, note="done")
    logger.log_event(
        agent_spec,
        state,
        "waiting_llm",
        details={"has_screenshot": True, "base64_chars": 12},
        note="ожидание ответа LLM",
    )

    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    jsonl = Path(paths["jsonl"]).read_text(encoding="utf-8").strip().splitlines()
    snapshot = Path(paths["snapshot"]).read_text(encoding="utf-8")

    assert "THINK" in md
    assert "outlook.read_calendar" in md
    assert "OBSERVE" in md
    assert "waiting_llm" in md
    assert len(jsonl) == 4
    assert "screenshot_base64" in snapshot
    assert "AAA" not in snapshot  # тяжёлое поле вырезано
    assert "omitted" in snapshot


def test_runtime_writes_transcript_during_run(tmp_path: Path) -> None:
    """LLMAgentLoopRuntime сохраняет трассировку на каждом шаге."""
    from tests.test_agent_loop_runtime import ScriptedPlanner, _finish_success

    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Сначала календарь",
            thought=AgentThought(
                understanding="Нужен календарь",
                planned_actions=["outlook.read_calendar"],
                why="источник встреч",
            ),
            tool_call={
                "tool_name": "outlook.read_calendar",
                "input_data": {},
                "reason": "данные",
            },
        ),
        _finish_success(
            "Готово",
            "Календарь прочитан, можно планировать фокус-блоки на неделю.",
            agent_spec,
        ),
    )
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    register_report_tools(registry, skip_existing=True)
    runtime = LLMAgentLoopRuntime(
        tool_gateway=ToolGateway(registry),
        agent_loop_planner=planner,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
        transcript_logger=RunTranscriptLogger(traces_root=tmp_path),
    )

    state = runtime.run(agent_spec, {"user_request": "график"})

    assert state.status == AgentRunStatus.COMPLETED
    paths = state.variables.get("run_transcript_paths")
    assert isinstance(paths, dict)
    md_path = Path(paths["markdown"])
    assert md_path.exists()
    text = md_path.read_text(encoding="utf-8")
    assert "THINK" in text
    assert "outlook.read_calendar" in text
    assert "waiting_llm" in text
    assert "llm_ready" in text
    assert "loop_finished" in text or "completed" in text.casefold()
