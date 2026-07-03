"""LLM-управляемый цикл выполнения агента (ReAct-style) без статического графа."""

from __future__ import annotations

import json
from typing import Callable
from uuid import uuid4

from agent_desktop_constructor.app.core.models.run_events import AgentRunEventType
from agent_desktop_constructor.app.llm.agent_loop_planner import LLMAgentLoopPlanner
from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.tooling import ToolCallResult
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    HumanApprovalRequest,
)
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.catalog import ToolsCatalog
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry

CALL_DECISIONS = {
    SupervisorDecisionType.CALL_TOOL,
    SupervisorDecisionType.CALL_ADDITIONAL_TOOL,
    SupervisorDecisionType.CONTINUE_TO_NEXT,
    SupervisorDecisionType.RETRY_TOOL,
}


class LLMAgentLoopRuntime(SimpleAgentRuntime):
    """Runtime, в котором LLM сама выбирает инструменты, смотрит результат и решает дальше."""

    def __init__(
        self,
        tool_gateway: ToolGateway,
        agent_loop_planner: LLMAgentLoopPlanner,
        tools_catalog: ToolsCatalog,
        tool_registry: ToolRegistry,
        run_repository: object | None = None,
        audit_repository: object | None = None,
        run_event_repository: object | None = None,
        human_approval_repository: object | None = None,
        max_repeat_attempts: int = 2,
    ) -> None:
        """Создать LLM-управляемый runtime без прямого доступа LLM к инструментам."""
        super().__init__(
            tool_gateway=tool_gateway,
            run_repository=run_repository,
            audit_repository=audit_repository,
            run_event_repository=run_event_repository,
            human_approval_repository=human_approval_repository,
        )
        self._planner = agent_loop_planner
        self._tools_catalog = tools_catalog
        self._tool_registry = tool_registry
        self._max_repeat_attempts = max_repeat_attempts
        self._progress_callback: Callable[[str], None] | None = None

    def set_progress_callback(
        self,
        callback: Callable[[str], None] | None,
    ) -> None:
        """Задать колбэк живого прогресса (текст LLM/инструментов) для UI."""
        self._progress_callback = callback

    def _emit_progress(self, message: str) -> None:
        """Отправить строку прогресса в UI, не роняя выполнение при ошибке колбэка."""
        callback = self._progress_callback
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            pass

    def _emit_decision_progress(self, decision: SupervisorDecision) -> None:
        """Транслировать в UI текст решения LLM (полностью, без обрезки)."""
        reason = (decision.reason or "").strip()
        if reason:
            self._emit_progress(f"🧠 LLM: {reason}")
        if decision.tool_call is not None:
            tool_reason = (decision.tool_call.reason or "").strip()
            suffix = f" — {tool_reason}" if tool_reason else ""
            self._emit_progress(
                f"→ LLM выбрала инструмент {decision.tool_call.tool_name}{suffix}"
            )
        final_message = (decision.final_message or "").strip()
        if final_message:
            self._emit_progress(f"✅ Итоговый вывод LLM: {final_message}")

    def run(
        self,
        agent_spec: AgentSpec,
        initial_variables: dict | None = None,
        run_id: str | None = None,
    ) -> AgentRuntimeState:
        """Исполнять цель агента через LLM-цикл до finish/pause/лимита."""
        state = AgentRuntimeState(
            run_id=run_id or str(uuid4()),
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.RUNNING,
            current_node_id="llm_loop",
            variables=initial_variables or {},
        )
        state.variables.setdefault("tool_outputs", {})
        self._create_run(agent_spec, state)
        self._add_run_event(
            state,
            AgentRunEventType.RUN_STARTED,
            "Запуск LLM-управляемого агента начат",
            details={"agent_id": agent_spec.agent_id},
        )
        self._emit_progress(f"▶ Запуск агента «{agent_spec.name}». Цель: {agent_spec.goal.main_goal}")

        executed_signatures: list[str] = []
        repeat_notes: list[str] = []
        repeat_count = 0
        limits = agent_spec.runtime_limits

        while state.can_continue(limits.max_steps, limits.max_tool_calls):
            state.step_counter += 1
            self._emit_progress(
                f"🧠 Шаг {state.step_counter}: LLM планирует следующее действие…"
            )
            try:
                decision = self._planner.decide(
                    agent_spec,
                    state,
                    executed_signatures=list(executed_signatures),
                    repeat_notes=list(repeat_notes),
                )
            except Exception as exc:
                state.mark_failed(f"LLM не смог принять решение: {exc}")
                self._add_run_event(
                    state,
                    AgentRunEventType.NODE_FAILED,
                    "LLM не смог принять решение шага",
                    details={"error": str(exc)},
                )
                self._emit_progress(f"⚠ LLM не смогла принять решение: {exc}")
                break

            state.variables.setdefault("loop_decisions", []).append(
                decision.model_dump(mode="json")
            )
            self._emit_decision_progress(decision)

            stop = self._apply_loop_decision(
                agent_spec=agent_spec,
                state=state,
                decision=decision,
                executed_signatures=executed_signatures,
                repeat_notes=repeat_notes,
            )
            if stop == "repeat":
                repeat_count += 1
                if repeat_count > self._max_repeat_attempts:
                    state.mark_failed(
                        "Агент зациклился: повторяет уже пройденные действия"
                    )
                    break
                continue
            if stop:
                break

        if state.status == AgentRunStatus.RUNNING:
            state.mark_failed("Достигнут лимит шагов без завершения цели")

        state.variables["loop_repeat_notes"] = repeat_notes
        self._add_terminal_event(state)
        self._save_checkpoint(state)
        return state

    def _apply_loop_decision(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
        executed_signatures: list[str],
        repeat_notes: list[str],
    ) -> bool | str:
        """Применить решение LLM. Вернуть True=стоп, False=продолжить, 'repeat'=повтор."""
        decision_type = decision.decision_type

        if decision_type == SupervisorDecisionType.FINISH_SUCCESS:
            state.variables["final_message"] = decision.final_message
            state.mark_completed()
            return True

        if decision_type == SupervisorDecisionType.FINISH_FAILED:
            state.mark_failed(decision.reason)
            return True

        if decision_type == SupervisorDecisionType.ASK_HUMAN:
            state.pause_for_human(
                HumanApprovalRequest(
                    approval_id=str(uuid4()),
                    node_id="llm_loop",
                    tool_name=None,
                    question=decision.human_question or decision.reason,
                    options=decision.human_options or ["Продолжить", "Остановить"],
                    status="pending",
                )
            )
            self._persist_human_approval_request(
                state,
                details={"source": "llm_agent_loop"},
            )
            return True

        if decision_type == SupervisorDecisionType.REQUEST_CREDENTIALS:
            state.pause_for_credentials(decision.reason)
            self._add_run_event(
                state,
                AgentRunEventType.HUMAN_APPROVAL_REQUESTED,
                "Агент ожидает credentials вне LLM-контекста",
                details={"reason": decision.reason},
            )
            return True

        if decision_type in CALL_DECISIONS:
            if decision.tool_call is None:
                state.mark_failed("LLM не выбрал инструмент и не завершил задачу")
                return True
            return self._handle_tool_call(
                agent_spec=agent_spec,
                state=state,
                decision=decision,
                executed_signatures=executed_signatures,
                repeat_notes=repeat_notes,
            )

        state.mark_failed(f"Неподдерживаемое решение LLM: {decision_type.value}")
        return True

    def _handle_tool_call(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
        executed_signatures: list[str],
        repeat_notes: list[str],
    ) -> bool | str:
        """Проверить, дедуплицировать и безопасно исполнить предложенный инструмент."""
        proposal = decision.tool_call
        signature = _action_signature(proposal.tool_name, proposal.input_data)
        if signature in executed_signatures:
            note = (
                f"Действие {proposal.tool_name} с теми же параметрами уже выполнялось "
                "— повтор пропущен."
            )
            repeat_notes.append(note)
            self._add_run_event(
                state,
                AgentRunEventType.NODE_FAILED,
                "LLM предложила повтор уже пройденного действия",
                tool_name=proposal.tool_name,
                details={"signature": signature},
            )
            return "repeat"

        validation_error = self._validate_tool_call(agent_spec, proposal.tool_name)
        if validation_error is not None:
            note = (
                f"Инструмент {proposal.tool_name} недоступен: {validation_error}. "
                "Выбери другой инструмент из доступных или заверши задачу."
            )
            repeat_notes.append(note)
            self._record_tool_result(
                state,
                {"proposed_input": proposal.input_data},
                ToolCallResult(
                    ok=False,
                    tool_name=proposal.tool_name,
                    error_type="TOOL_NOT_AVAILABLE",
                    error_message=validation_error,
                ),
            )
            self._add_run_event(
                state,
                AgentRunEventType.TOOL_CALL_FAILED,
                f"LLM предложила недоступный инструмент {proposal.tool_name}",
                tool_name=proposal.tool_name,
                details={"error": validation_error},
            )
            return "repeat"

        executed_signatures.append(signature)
        self._execute_loop_tool(
            agent_spec=agent_spec,
            state=state,
            tool_name=proposal.tool_name,
            proposed_input=proposal.input_data,
            reason=proposal.reason,
        )
        if state.status in {
            AgentRunStatus.PAUSED_FOR_HUMAN,
            AgentRunStatus.PAUSED_FOR_CREDENTIALS,
            AgentRunStatus.FAILED,
        }:
            return True
        return False

    def _execute_loop_tool(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        tool_name: str,
        proposed_input: dict,
        reason: str,
    ) -> None:
        """Исполнить инструмент через ToolGateway и записать результат для LLM."""
        input_data = {
            **proposed_input,
            "llm_reason": reason,
            "user_request": state.variables.get("user_request"),
            "agent_goal": agent_spec.goal.model_dump(mode="json"),
            "tool_outputs": state.variables.get("tool_outputs", {}),
            "runtime_context": {
                "run_id": state.run_id,
                "agent_id": state.agent_id,
                "step_counter": state.step_counter,
            },
        }
        self._add_run_event(
            state,
            AgentRunEventType.TOOL_CALL_STARTED,
            f"LLM запросила инструмент {tool_name}",
            tool_name=tool_name,
            details={"reason": reason},
        )
        result = self._tool_gateway.execute_tool(
            agent_spec=agent_spec,
            run_id=state.run_id,
            tool_name=tool_name,
            input_data=input_data,
            human_approved=False,
        )

        if result.requires_human_approval:
            state.pause_for_human(
                HumanApprovalRequest(
                    approval_id=str(uuid4()),
                    node_id="llm_loop",
                    tool_name=tool_name,
                    question=f"Инструмент {tool_name} требует подтверждения. Выполнить?",
                    options=["Подтвердить", "Отклонить"],
                    status="pending",
                )
            )
            self._persist_human_approval_request(
                state,
                details={"source": "llm_agent_loop", "error_type": result.error_type},
            )
            return

        self._record_tool_result(state, input_data, result)
        if result.ok:
            state.variables.setdefault("tool_outputs", {})[tool_name] = (
                result.output_data or {}
            )
            output_keys = sorted((result.output_data or {}).keys())
            self._add_run_event(
                state,
                AgentRunEventType.TOOL_CALL_COMPLETED,
                f"Инструмент {tool_name} выполнен",
                tool_name=tool_name,
                details={"output_keys": output_keys},
            )
            self._emit_progress(
                f"✓ Инструмент {tool_name} выполнен. Данные: "
                f"{', '.join(output_keys) if output_keys else 'нет полей'}"
            )
            return

        self._add_run_event(
            state,
            AgentRunEventType.TOOL_CALL_FAILED,
            f"Инструмент {tool_name} завершился ошибкой (LLM решит следующий шаг)",
            tool_name=tool_name,
            details={
                "error_type": result.error_type,
                "error_message": result.error_message,
            },
        )
        self._emit_progress(
            f"✕ Инструмент {tool_name} ошибка "
            f"[{result.error_type or 'ERROR'}]: {result.error_message or ''}"
        )

    def _validate_tool_call(
        self,
        agent_spec: AgentSpec,
        tool_name: str,
    ) -> str | None:
        """Проверить предложенный LLM инструмент до ToolGateway."""
        if not self._tools_catalog.has_tool(tool_name):
            return f"Инструмент {tool_name!r} отсутствует в ToolsCatalog"
        if not self._tool_registry.has_tool(tool_name):
            return f"Инструмент {tool_name!r} не зарегистрирован в ToolRegistry"
        if tool_name not in agent_spec.allowed_tool_names():
            return f"Инструмент {tool_name!r} не разрешён в AgentSpec"
        return None


def _action_signature(tool_name: str, input_data: dict) -> str:
    """Построить сигнатуру действия для защиты от повторов одинаковых путей."""
    try:
        payload = json.dumps(input_data, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = str(input_data)
    return f"{tool_name}::{payload}"
