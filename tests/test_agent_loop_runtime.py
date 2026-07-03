"""Тесты LLMAgentLoopRuntime: LLM сама ведёт инструменты и делает вывод."""

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
from agent_desktop_constructor.tools.report_tools import register_report_tools


class ScriptedPlanner:
    """Fake LLM-планировщик, отдающий заранее заданные решения."""

    def __init__(self, *decisions: SupervisorDecision) -> None:
        self.decisions = list(decisions)
        self.calls = 0
        self.seen_signatures: list[list[str]] = []

    def decide(self, agent_spec, runtime_state, executed_signatures=None, repeat_notes=None):
        """Вернуть следующее сценарное решение."""
        self.calls += 1
        self.seen_signatures.append(list(executed_signatures or []))
        if self.decisions:
            return self.decisions.pop(0)
        return SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_FAILED,
            reason="Сценарий исчерпан",
        )


def make_runtime(planner) -> LLMAgentLoopRuntime:
    """Собрать LLM-цикл с fake registry."""
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    register_report_tools(registry, skip_existing=True)
    return LLMAgentLoopRuntime(
        tool_gateway=ToolGateway(registry),
        agent_loop_planner=planner,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )


def test_llm_drives_tools_and_makes_its_own_conclusion() -> None:
    """LLM вызывает инструмент, видит результат и сама формулирует вывод."""
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Сначала прочитать календарь",
            tool_call={
                "tool_name": "outlook.read_calendar",
                "input_data": {},
                "reason": "Нужны совещания",
            },
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Данных достаточно",
            final_message="На неделе одно совещание, есть окно для фокус-работы.",
        ),
    )
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})

    assert state.status == AgentRunStatus.COMPLETED
    assert state.variables["final_message"] == (
        "На неделе одно совещание, есть окно для фокус-работы."
    )
    executed = [record.tool_name for record in state.tool_results]
    assert "outlook.read_calendar" in executed
    assert "outlook.read_calendar" in state.variables["tool_outputs"]


def test_llm_loop_does_not_repeat_same_path() -> None:
    """Повтор того же действия дедуплицируется, а зацикливание завершает run."""
    repeated = SupervisorDecision(
        decision_type=SupervisorDecisionType.CALL_TOOL,
        reason="Снова тот же инструмент",
        tool_call={
            "tool_name": "outlook.read_calendar",
            "input_data": {},
            "reason": "повтор",
        },
    )
    planner = ScriptedPlanner(repeated, repeated, repeated, repeated, repeated)
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})

    assert state.status == AgentRunStatus.FAILED
    executed = [record.tool_name for record in state.tool_results]
    assert executed.count("outlook.read_calendar") == 1
    assert any("зациклил" in error.casefold() for error in state.errors)


def test_llm_loop_rejects_unknown_tool_and_lets_llm_recover() -> None:
    """Неизвестный инструмент не исполняется; LLM получает ошибку и завершает сама."""
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Неизвестный инструмент",
            tool_call={
                "tool_name": "invented.tool",
                "input_data": {},
                "reason": "bad",
            },
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Инструмент недоступен, завершаю с тем что есть",
            final_message="Не удалось выполнить недоступный инструмент.",
        ),
    )
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать"})

    assert state.status == AgentRunStatus.COMPLETED
    assert "invented.tool" not in state.variables["tool_outputs"]
    invented = [r for r in state.tool_results if r.tool_name == "invented.tool"]
    assert invented and invented[0].ok is False
    assert "ToolsCatalog" in (invented[0].error_message or "")


def test_llm_loop_stops_when_cancel_requested() -> None:
    """Если cancel_callback возвращает True, цикл останавливается до планирования."""
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Не должно выполниться",
            tool_call={
                "tool_name": "outlook.read_calendar",
                "input_data": {},
                "reason": "нет",
            },
        )
    )
    runtime = make_runtime(planner)
    runtime.set_cancel_callback(lambda: True)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})

    assert state.status == AgentRunStatus.CANCELLED
    assert planner.calls == 0
    assert state.variables.get("cancel_reason")


def test_llm_loop_cancel_after_first_step() -> None:
    """Отмена срабатывает между шагами: первый инструмент выполнен, затем стоп."""
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Прочитать календарь",
            tool_call={
                "tool_name": "outlook.read_calendar",
                "input_data": {},
                "reason": "данные",
            },
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Не должно дойти сюда",
            final_message="не используется",
        ),
    )
    runtime = make_runtime(planner)
    runtime.set_cancel_callback(cancel)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})

    assert state.status == AgentRunStatus.CANCELLED
    assert planner.calls == 1


def test_llm_loop_ask_human_pauses_and_resumes_without_restart() -> None:
    """ask_human приостанавливает цикл, а resume продолжает с ответом человека."""
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.ASK_HUMAN,
            reason="После ответа продолжу анализ",
            human_question="Какую неделю анализировать?",
            human_options=["Текущую", "Прошлую"],
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Ответ получен",
            final_message="Готово, использовал ответ человека.",
        ),
    )
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})
    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert state.variables.get("human_plan_ahead") == "После ответа продолжу анализ"

    resumed = runtime.resume_with_human_input(agent_spec, state, "Текущую")

    assert resumed.status == AgentRunStatus.COMPLETED
    assert resumed.variables["final_message"] == "Готово, использовал ответ человека."
    responses = resumed.variables.get("human_responses")
    assert responses and responses[-1]["answer"] == "Текущую"


def test_llm_loop_resume_executes_approved_tool() -> None:
    """После подтверждения человека отложенный dangerous-инструмент исполняется."""
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Попробовать отправку",
            tool_call={
                "tool_name": "email.send",
                "input_data": {},
                "reason": "dangerous",
            },
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Отправлено",
            final_message="Письмо обработано после подтверждения.",
        ),
    )
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Найди поручения и отправь отчёт по почте"
    )

    state = runtime.run(agent_spec, {"user_request": "поручения"})
    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.variables.get("pending_loop_tool", {}).get("tool_name") == "email.send"

    resumed = runtime.resume_with_human_input(agent_spec, state, "Подтвердить")

    assert resumed.status == AgentRunStatus.COMPLETED
    sent = [r for r in resumed.tool_results if r.tool_name == "email.send"]
    assert sent and sent[0].ok is True


def _blank_state() -> AgentRuntimeState:
    """Пустое состояние для unit-проверок vision-прогресса."""
    return AgentRuntimeState(
        run_id="run-vision",
        agent_id="agent-vision",
        status=AgentRunStatus.RUNNING,
    )


def test_vision_scroll_without_move_sets_no_progress_note() -> None:
    """scrolled=false помечается как отсутствие прогресса, чтобы прервать повтор."""
    runtime = make_runtime(ScriptedPlanner())
    state = _blank_state()

    runtime._track_vision_progress(
        state,
        "browser.scroll",
        {"direction": "down"},
        {
            "url": "https://web.telegram.org",
            "title": "Telegram",
            "scrolled": False,
            "at_bottom": True,
            "scroll_target": "div.chat-list",
        },
    )

    note = state.variables.get("_vision_no_progress_note")
    assert note is not None
    assert "scroll" in note.lower()


def test_vision_repeated_identical_state_sets_no_progress_note() -> None:
    """Повтор действия с тем же отпечатком страницы помечается как без прогресса."""
    runtime = make_runtime(ScriptedPlanner())
    state = _blank_state()
    output = {
        "url": "https://web.telegram.org",
        "title": "Telegram",
        "scroll_top": 4100,
        "scroll_left": 0,
        "scrolled": True,
    }

    runtime._track_vision_progress(state, "browser.click", {"x": 10, "y": 20}, output)
    assert state.variables.get("_vision_no_progress_note") is None

    runtime._track_vision_progress(state, "browser.click", {"x": 10, "y": 20}, output)
    assert state.variables.get("_vision_no_progress_note") is not None


def test_llm_loop_dangerous_tool_requires_human_approval() -> None:
    """Dangerous-инструмент уходит на HumanApproval через ToolGateway."""
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Попробовать отправку",
            tool_call={
                "tool_name": "email.send",
                "input_data": {},
                "reason": "dangerous",
            },
        )
    )
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Найди поручения и отправь отчёт по почте"
    )

    state = runtime.run(agent_spec, {"user_request": "поручения"})

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert state.pending_human_approval.tool_name == "email.send"
