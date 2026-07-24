"""Тесты LLMAgentLoopRuntime: LLM сама ведёт инструменты и делает вывод."""

from pathlib import Path

from agent_desktop_constructor.app.llm.errors import LLMCancelledError
from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.app.runtime.agent_loop_runtime import (
    DEFAULT_CODE_RUN_AUTO_APPROVE_BUDGET,
    LLMAgentLoopRuntime,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.agent_workspace import AgentWorkspaceResolver
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.code_execution_tools import (
    register_code_execution_tools,
)
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.report_tools import register_report_tools


def _finish_success(reason: str, final_message: str, agent_spec: AgentSpec) -> SupervisorDecision:
    """finish_success с criteria_evidence по всем критериям спеки."""
    evidence = [
        {
            "criterion": criterion,
            "evidence": f"Подтверждено результатом инструментов: {final_message[:80]}",
        }
        for criterion in agent_spec.goal.success_criteria
    ]
    if not evidence:
        evidence = [
            {
                "criterion": agent_spec.goal.main_goal,
                "evidence": f"Подтверждено результатом инструментов: {final_message[:80]}",
            }
        ]
    return SupervisorDecision(
        decision_type=SupervisorDecisionType.FINISH_SUCCESS,
        reason=reason,
        final_message=final_message,
        criteria_evidence=evidence,
    )


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


class CancellingPlanner:
    """Планировщик, имитирующий прерывание HTTP-запроса к LLM."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, agent_spec, runtime_state, executed_signatures=None, repeat_notes=None):
        self.calls += 1
        raise LLMCancelledError("Запрос к LLM отменён пользователем")


class PlannerWithCancellableClient:
    """Планировщик с LLM-клиентом, принимающим set_cancel_callback."""

    def __init__(self) -> None:
        self._llm_client = _FakeCancellableClient()
        self.calls = 0

    def decide(self, agent_spec, runtime_state, executed_signatures=None, repeat_notes=None):
        self.calls += 1
        return SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="ok",
            final_message="готово",
        )


class _FakeCancellableClient:
    def __init__(self) -> None:
        self.cancel_callback = None

    def set_cancel_callback(self, callback) -> None:
        self.cancel_callback = callback


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
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
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
        _finish_success(
            "Данных достаточно",
            "На неделе одно совещание, есть окно для фокус-работы.",
            agent_spec,
        ),
    )
    runtime = make_runtime(planner)

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})

    assert state.status == AgentRunStatus.COMPLETED
    assert state.variables["final_message"] == (
        "На неделе одно совещание, есть окно для фокус-работы."
    )
    executed = [record.tool_name for record in state.tool_results]
    assert "outlook.read_calendar" in executed
    assert "outlook.read_calendar" in state.variables["tool_outputs"]
    assert state.variables.get("goal_checklist")
    assert state.variables.get("tool_output_history")


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
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
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
        _finish_success(
            "Инструмент недоступен, завершаю с тем что есть",
            "Не удалось выполнить недоступный инструмент, данных календаря нет.",
            agent_spec,
        ),
    )
    runtime = make_runtime(planner)

    state = runtime.run(agent_spec, {"user_request": "распланировать"})

    assert state.status == AgentRunStatus.COMPLETED
    assert "invented.tool" not in state.variables["tool_outputs"]
    invented = [r for r in state.tool_results if r.tool_name == "invented.tool"]
    assert invented and invented[0].ok is False
    assert "ToolsCatalog" in (invented[0].error_message or "")


def test_finish_success_rejected_without_criteria_evidence() -> None:
    """Без criteria_evidence runtime отклоняет finish_success и даёт LLM ещё шаг."""
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.FINISH_SUCCESS,
            reason="Рано",
            final_message="Готово без доказательств по критериям цели.",
        ),
        _finish_success(
            "Теперь с evidence",
            "Календарь учтён: одно совещание, можно планировать фокус-блоки.",
            agent_spec,
        ),
    )
    runtime = make_runtime(planner)

    state = runtime.run(agent_spec, {"user_request": "график"})

    assert state.status == AgentRunStatus.COMPLETED
    assert planner.calls == 2
    assert any(
        "criteria_evidence" in note or "критери" in note.casefold()
        for note in state.variables.get("loop_repeat_notes", [])
    )


def test_failed_tool_can_be_retried_with_same_signature() -> None:
    """После ошибки тот же tool с теми же params можно повторить (signature только на success)."""
    from agent_desktop_constructor.core.models.tooling import ToolCallResult

    class FlakyGateway(ToolGateway):
        def __init__(self, registry: ToolRegistry) -> None:
            super().__init__(registry)
            self.calls = 0

        def execute_tool(self, **kwargs):  # noqa: ANN003
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(
                    ok=False,
                    tool_name=kwargs["tool_name"],
                    error_type="TRANSIENT",
                    error_message="временный сбой",
                )
            return super().execute_tool(**kwargs)

    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="попытка 1",
            tool_call={
                "tool_name": "outlook.read_calendar",
                "input_data": {},
                "reason": "календарь",
            },
        ),
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="попытка 2",
            tool_call={
                "tool_name": "outlook.read_calendar",
                "input_data": {},
                "reason": "календарь снова",
            },
        ),
        _finish_success(
            "ок",
            "Календарь прочитан со второй попытки, график можно строить.",
            agent_spec,
        ),
    )
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    register_report_tools(registry, skip_existing=True)
    gateway = FlakyGateway(registry)
    runtime = LLMAgentLoopRuntime(
        tool_gateway=gateway,
        agent_loop_planner=planner,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )

    state = runtime.run(agent_spec, {"user_request": "график"})

    assert state.status == AgentRunStatus.COMPLETED
    assert gateway.calls == 2
    calendar = [r for r in state.tool_results if r.tool_name == "outlook.read_calendar"]
    assert len(calendar) == 2
    assert calendar[0].ok is False and calendar[1].ok is True
    history = state.variables.get("tool_output_history") or []
    assert len(history) >= 2


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


def test_llm_loop_cancels_when_planner_raises_cancelled() -> None:
    """Если HTTP к модели прерван, цикл помечает run как CANCELLED, а не FAILED."""
    planner = CancellingPlanner()
    runtime = make_runtime(planner)
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})

    assert state.status == AgentRunStatus.CANCELLED
    assert planner.calls == 1
    assert state.variables.get("cancel_reason")


def test_set_cancel_callback_wires_llm_client() -> None:
    """set_cancel_callback пробрасывает колбэк в LLM-клиент планировщика."""
    planner = PlannerWithCancellableClient()
    runtime = make_runtime(planner)
    cb = lambda: False
    runtime.set_cancel_callback(cb)
    assert planner._llm_client.cancel_callback is cb
    runtime.set_cancel_callback(None)
    assert planner._llm_client.cancel_callback is None


def test_llm_loop_ask_human_pauses_and_resumes_without_restart() -> None:
    """ask_human приостанавливает цикл, а resume продолжает с ответом человека."""
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.ASK_HUMAN,
            reason="После ответа продолжу анализ",
            human_question="Какую неделю анализировать?",
            human_options=["Текущую", "Прошлую"],
        ),
        _finish_success(
            "Ответ получен",
            "Готово, использовал ответ человека для планирования недели.",
            agent_spec,
        ),
    )
    runtime = make_runtime(planner)

    state = runtime.run(agent_spec, {"user_request": "распланировать график"})
    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert state.variables.get("human_plan_ahead") == "После ответа продолжу анализ"

    resumed = runtime.resume_with_human_input(agent_spec, state, "Текущую")

    assert resumed.status == AgentRunStatus.COMPLETED
    assert resumed.variables["final_message"] == (
        "Готово, использовал ответ человека для планирования недели."
    )
    responses = resumed.variables.get("human_responses")
    assert responses and responses[-1]["answer"] == "Текущую"


def test_llm_loop_resume_executes_approved_tool() -> None:
    """После подтверждения человека отложенный dangerous-инструмент исполняется."""
    agent_spec = AgentBuilder().build_from_request(
        "Найди поручения и отправь отчёт по почте"
    )
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
        _finish_success(
            "Отправлено",
            "Письмо обработано после подтверждения человеком.",
            agent_spec,
        ),
    )
    runtime = make_runtime(planner)

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


def _with_code_run_tool(agent_spec: AgentSpec) -> AgentSpec:
    """Добавить code.run_python в разрешения агента."""
    tools = list(agent_spec.tools)
    if not any(tool.tool_name == "code.run_python" for tool in tools):
        tools.append(
            AgentToolPermission(
                tool_name="code.run_python",
                action_level=AgentActionLevel.CREATE_DRAFT,
                requires_human_approval=True,
                allowed=True,
            )
        )
    return agent_spec.model_copy(update={"tools": tools})


def test_finish_success_rejected_on_low_confidence() -> None:
    """Явно низкая confidence блокирует finish_success."""
    agent_spec = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    low = _finish_success(
        "Сомневаюсь",
        "Календарь вроде прочитан, но уверенность низкая для финального ответа.",
        agent_spec,
    ).model_copy(update={"confidence": 0.1})
    high = _finish_success(
        "Уверен",
        "Календарь прочитан, одно совещание, можно планировать фокус-блоки.",
        agent_spec,
    ).model_copy(update={"confidence": 0.9})
    planner = ScriptedPlanner(low, high)
    runtime = make_runtime(planner)

    state = runtime.run(agent_spec, {"user_request": "график"})

    assert state.status == AgentRunStatus.COMPLETED
    assert planner.calls == 2
    assert any("confidence" in note for note in state.variables.get("loop_repeat_notes", []))


def test_code_run_python_auto_approved_within_budget(tmp_path: Path) -> None:
    """code.run_python в LLM-цикле автоподтверждается, пока есть sandbox-бюджет."""
    agent_spec = _with_code_run_tool(
        AgentBuilder().build_from_request(
            "Посмотри совещания в Outlook и подскажи как распланировать график"
        )
    )
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Запускаю парсер",
            tool_call={
                "tool_name": "code.run_python",
                "input_data": {
                    "filename": "parse.py",
                    "code": "print('hello-from-agent')",
                },
                "reason": "обработка",
            },
        ),
        _finish_success(
            "Готово",
            "Скрипт выполнен, stdout получен, цель по обработке данных закрыта.",
            agent_spec,
        ),
    )
    registry = ToolRegistry()
    register_code_execution_tools(registry, AgentWorkspaceResolver(tmp_path))
    runtime = LLMAgentLoopRuntime(
        tool_gateway=ToolGateway(registry),
        agent_loop_planner=planner,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )

    state = runtime.run(
        agent_spec,
        {"user_request": "обработать данные скриптом"},
    )

    assert state.status == AgentRunStatus.COMPLETED
    assert state.variables["code_run_auto_approve_budget"] == (
        DEFAULT_CODE_RUN_AUTO_APPROVE_BUDGET - 1
    )
    assert "parse.py" in state.variables.get("code_run_approved_files", [])
    runs = [r for r in state.tool_results if r.tool_name == "code.run_python"]
    assert runs and runs[0].ok is True


def test_code_run_python_pauses_when_budget_exhausted(tmp_path: Path) -> None:
    """При нулевом бюджете code.run_python снова требует HumanApproval."""
    agent_spec = _with_code_run_tool(
        AgentBuilder().build_from_request(
            "Посмотри совещания в Outlook и подскажи как распланировать график"
        )
    )
    planner = ScriptedPlanner(
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_TOOL,
            reason="Запускаю без бюджета",
            tool_call={
                "tool_name": "code.run_python",
                "input_data": {
                    "filename": "once.py",
                    "code": "print(1)",
                },
                "reason": "run",
            },
        )
    )
    registry = ToolRegistry()
    register_code_execution_tools(registry, AgentWorkspaceResolver(tmp_path))
    runtime = LLMAgentLoopRuntime(
        tool_gateway=ToolGateway(registry),
        agent_loop_planner=planner,
        tools_catalog=load_tools_catalog(),
        tool_registry=registry,
    )

    state = runtime.run(
        agent_spec,
        {
            "user_request": "скрипт",
            "code_run_auto_approve_budget": 0,
            "code_run_approved_files": [],
        },
    )

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.variables.get("pending_loop_tool", {}).get("tool_name") == (
        "code.run_python"
    )
