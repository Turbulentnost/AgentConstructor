"""LLM-управляемый цикл выполнения агента (ReAct-style) без статического графа."""

from __future__ import annotations

import json
from typing import Callable
from uuid import uuid4

from agent_desktop_constructor.app.context.manager import AgentContextManager
from agent_desktop_constructor.app.core.models.human_approval import (
    HumanApprovalStatus,
)
from agent_desktop_constructor.app.core.models.run_events import AgentRunEventType
from agent_desktop_constructor.app.llm.agent_loop_planner import LLMAgentLoopPlanner
from agent_desktop_constructor.app.llm.errors import LLMCancelledError
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
from agent_desktop_constructor.tools.wait_tool import WAIT_TOOL_NAME

CALL_DECISIONS = {
    SupervisorDecisionType.CALL_TOOL,
    SupervisorDecisionType.CALL_ADDITIONAL_TOOL,
    SupervisorDecisionType.CONTINUE_TO_NEXT,
    SupervisorDecisionType.RETRY_TOOL,
}

# Vision-инструменты меняют состояние UI, поэтому повтор одного и того же действия
# (например ещё раз прокрутить или сделать скриншот) допустим — LLM видит новый кадр.
VISION_INTERACTION_TOOLS = {
    "browser.navigate",
    "browser.screenshot",
    "browser.click",
    "browser.type_text",
    "browser.press_key",
    "browser.scroll",
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
        max_decision_retries: int = 3,
        context_manager: AgentContextManager | None = None,
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
        self._max_decision_retries = max_decision_retries
        self._context_manager = context_manager or AgentContextManager()
        self._progress_callback: Callable[[str], None] | None = None
        self._cancel_callback: Callable[[], bool] | None = None

    def set_progress_callback(
        self,
        callback: Callable[[str], None] | None,
    ) -> None:
        """Задать колбэк живого прогресса (текст LLM/инструментов) для UI."""
        self._progress_callback = callback

    def set_cancel_callback(
        self,
        callback: Callable[[], bool] | None,
    ) -> None:
        """Задать колбэк отмены: цикл и текущий HTTP-запрос к LLM могут прерваться."""
        self._cancel_callback = callback
        self._sync_llm_cancel_callback(callback)

    def _sync_llm_cancel_callback(
        self,
        callback: Callable[[], bool] | None,
    ) -> None:
        """Пробросить отмену в LLM-клиент планировщика, если он это поддерживает."""
        llm_client = getattr(self._planner, "_llm_client", None)
        if llm_client is None:
            return
        if hasattr(llm_client, "set_cancel_callback"):
            try:
                llm_client.set_cancel_callback(callback)
            except Exception:
                pass

    def _is_cancel_requested(self) -> bool:
        """Проверить, запросил ли пользователь остановку (безопасно к ошибкам)."""
        callback = self._cancel_callback
        if callback is None:
            return False
        try:
            return bool(callback())
        except Exception:
            return False

    def _mark_user_cancelled(self, state: AgentRuntimeState) -> None:
        """Пометить run как отменённый пользователем и сообщить в UI."""
        state.mark_cancelled("Выполнение остановлено пользователем")
        self._add_run_event(
            state,
            AgentRunEventType.NODE_FAILED,
            "Выполнение остановлено пользователем",
            details={"reason": "user_stop"},
        )
        self._emit_progress("⏹ Выполнение остановлено пользователем.")

    def _emit_progress(
        self,
        message: str,
        state: AgentRuntimeState | None = None,
        agent_spec: AgentSpec | None = None,
    ) -> None:
        """Отправить строку прогресса в UI и сохранить её в контексте run."""
        if state is not None:
            self._record_live_progress_event(state, message, agent_spec)
        callback = self._progress_callback
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            pass

    def _record_live_progress_event(
        self,
        state: AgentRuntimeState,
        message: str,
        agent_spec: AgentSpec | None = None,
    ) -> None:
        """Сохранить live-событие, чтобы следующий LLM шаг видел историю чата."""
        events = state.variables.setdefault("live_progress_events", [])
        if not isinstance(events, list):
            events = []
            state.variables["live_progress_events"] = events
        events.append(
            {
                "step": state.step_counter,
                "message": message,
            }
        )
        del events[:-80]
        self._refresh_context(state, agent_spec, emit_usage=False)

    def _emit_think_progress(
        self,
        decision: SupervisorDecision,
        state: AgentRuntimeState | None = None,
        agent_spec: AgentSpec | None = None,
    ) -> None:
        """Показать в UI отдельный этап THINK перед действием агента."""
        thought = decision.thought
        if thought is None:
            return
        parts: list[str] = []
        if (thought.understanding or "").strip():
            parts.append(f"понял: {thought.understanding.strip()}")
        if (thought.missing_info or "").strip():
            parts.append(f"не хватает: {thought.missing_info.strip()}")
        actions = [a.strip() for a in thought.planned_actions if a and a.strip()]
        if actions:
            parts.append("план: " + "; ".join(actions))
        why = (thought.why or "").strip()
        if thought.chosen_tool:
            suffix = f" — {why}" if why else ""
            parts.append(f"выбираю: {thought.chosen_tool}{suffix}")
        elif why:
            parts.append(f"почему: {why}")
        if parts:
            self._emit_progress("🤔 THINK: " + " | ".join(parts), state, agent_spec)

    def _emit_decision_progress(
        self,
        decision: SupervisorDecision,
        state: AgentRuntimeState | None = None,
        agent_spec: AgentSpec | None = None,
    ) -> None:
        """Транслировать в UI текст решения LLM (полностью, без обрезки)."""
        reason = (decision.reason or "").strip()
        if reason:
            self._emit_progress(f"🧠 LLM: {reason}", state, agent_spec)
        if decision.tool_call is not None:
            tool_reason = (decision.tool_call.reason or "").strip()
            suffix = f" — {tool_reason}" if tool_reason else ""
            self._emit_progress(
                f"→ LLM выбрала инструмент {decision.tool_call.tool_name}{suffix}",
                state,
                agent_spec,
            )
        final_message = (decision.final_message or "").strip()
        if final_message:
            self._emit_progress(f"✅ Итоговый вывод LLM: {final_message}", state, agent_spec)

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
        self._refresh_context(state, agent_spec)
        self._create_run(agent_spec, state)
        self._add_run_event(
            state,
            AgentRunEventType.RUN_STARTED,
            "Запуск LLM-управляемого агента начат",
            details={"agent_id": agent_spec.agent_id},
        )
        self._emit_progress(
            f"▶ Запуск агента «{agent_spec.name}». Цель: {agent_spec.goal.main_goal}",
            state,
            agent_spec,
        )
        return self._drive_loop(agent_spec, state)

    def resume_with_human_input(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        human_message: str,
        approved: bool = True,
    ) -> AgentRuntimeState:
        """Продолжить приостановленный LLM-цикл после действия/ответа человека.

        Работа агента не начинается заново: сохранённое состояние (собранные
        данные, скриншоты, постоянная сессия браузера) остаётся живым, ответ
        человека добавляется в контекст, и цикл продолжает планирование.
        """
        if state.status not in {
            AgentRunStatus.PAUSED_FOR_HUMAN,
            AgentRunStatus.PAUSED_FOR_CREDENTIALS,
        }:
            return state

        answer = (human_message or "").strip()
        default_answer = "Подтвердить" if approved else "Отклонить"
        approval = state.pending_human_approval
        question = (
            approval.question
            if approval is not None
            else state.variables.get("credential_request_reason")
        )
        state.variables.setdefault("human_responses", []).append(
            {
                "question": question,
                "answer": answer or default_answer,
                "approved": approved,
                "step": state.step_counter,
            }
        )
        self._emit_progress(
            f"👤 Человек ответил: {answer or default_answer}. Продолжаю работу…"
        )
        self._refresh_context(state, agent_spec)

        pending_tool = state.variables.pop("pending_loop_tool", None)

        if state.status == AgentRunStatus.PAUSED_FOR_CREDENTIALS:
            state.variables.pop("credential_request_reason", None)
            state.mark_running("llm_loop")
        else:
            if approval is not None:
                self._answer_human_approval_record(
                    approval.approval_id,
                    HumanApprovalStatus.APPROVED
                    if approved
                    else HumanApprovalStatus.REJECTED,
                    answer or default_answer,
                    answer or None,
                )
                state.resume_after_human(answer or default_answer, answer or None)
            else:
                state.mark_running("llm_loop")

        self._add_run_event(
            state,
            AgentRunEventType.HUMAN_APPROVAL_ANSWERED,
            "Получен ответ человека — агент продолжает работу",
            details={"approved": approved, "answer": answer or default_answer},
        )
        self._refresh_context(state, agent_spec)

        if pending_tool is not None and approved:
            signature = _action_signature(
                pending_tool["tool_name"], pending_tool.get("input_data", {})
            )
            state.variables.setdefault("loop_executed_signatures", []).append(signature)
            self._execute_loop_tool(
                agent_spec=agent_spec,
                state=state,
                tool_name=pending_tool["tool_name"],
                proposed_input=pending_tool.get("input_data", {}),
                reason=pending_tool.get("reason", "Подтверждено человеком"),
                human_approved=True,
            )
            if state.status in {
                AgentRunStatus.PAUSED_FOR_HUMAN,
                AgentRunStatus.PAUSED_FOR_CREDENTIALS,
                AgentRunStatus.FAILED,
            }:
                self._add_terminal_event(state)
                self._save_checkpoint(state)
                return state

        return self._drive_loop(agent_spec, state)

    def _persist_loop_progress(
        self,
        state: AgentRuntimeState,
        executed_signatures: list[str],
        repeat_notes: list[str],
        repeat_count: int,
    ) -> None:
        """Сохранить прогресс цикла в state, чтобы resume мог его восстановить."""
        state.variables["loop_executed_signatures"] = list(executed_signatures)
        state.variables["loop_repeat_notes"] = list(repeat_notes)
        state.variables["loop_repeat_count"] = repeat_count

    def _refresh_context(
        self,
        state: AgentRuntimeState,
        agent_spec: AgentSpec | None = None,
        *,
        emit_usage: bool = True,
    ) -> None:
        """Обновить context_snapshot в state.variables без влияния на выполнение."""
        try:
            snapshot = self._context_manager.update_state_context(
                state,
                agent_spec=agent_spec,
            )
            if emit_usage:
                usage = snapshot.usage
                if usage is not None:
                    self._emit_context_usage(usage.model_dump(mode="json"))
        except Exception as exc:
            state.variables["context_snapshot_error"] = str(exc)

    def _emit_context_usage(self, usage: dict) -> None:
        """Отправить UI машинно-читаемое обновление индикатора контекста."""
        callback = self._progress_callback
        if callback is None:
            return
        try:
            callback("CTX_USAGE:" + json.dumps(usage, ensure_ascii=False, default=str))
        except Exception:
            pass

    def _drive_loop(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
    ) -> AgentRuntimeState:
        """Крутить ReAct-цикл LLM до finish/pause/лимита (общий для run и resume)."""
        executed_signatures: list[str] = list(
            state.variables.get("loop_executed_signatures", [])
        )
        repeat_notes: list[str] = list(state.variables.get("loop_repeat_notes", []))
        repeat_count = int(state.variables.get("loop_repeat_count", 0))
        limits = agent_spec.runtime_limits
        decision_failures = 0

        while state.can_continue(limits.max_steps, limits.max_tool_calls):
            if self._is_cancel_requested():
                self._mark_user_cancelled(state)
                break
            state.step_counter += 1
            self._emit_progress(
                f"🧠 Шаг {state.step_counter}: LLM планирует следующее действие…",
                state,
                agent_spec,
            )
            try:
                decision = self._planner.decide(
                    agent_spec,
                    state,
                    executed_signatures=list(executed_signatures),
                    repeat_notes=list(repeat_notes),
                )
            except LLMCancelledError:
                self._mark_user_cancelled(state)
                break
            except Exception as exc:
                if self._is_cancel_requested():
                    self._mark_user_cancelled(state)
                    break
                decision_failures += 1
                if decision_failures <= self._max_decision_retries:
                    hint = (
                        "На прошлом шаге твой JSON-ответ не прошёл проверку: "
                        f"{exc}. Верни строго валидный JSON решения: decision_type "
                        "— одно из значений схемы (call_tool/finish_success/…), а имя "
                        "инструмента только в tool_call.tool_name."
                    )
                    if hint not in repeat_notes:
                        repeat_notes.append(hint)
                    self._emit_progress(
                        f"⚠ Ответ LLM не прошёл проверку (попытка "
                        f"{decision_failures}/{self._max_decision_retries}), "
                        f"прошу переформулировать: {exc}"
                    )
                    continue
                state.mark_failed(f"LLM не смог принять решение: {exc}")
                self._add_run_event(
                    state,
                    AgentRunEventType.NODE_FAILED,
                    "LLM не смог принять решение шага",
                    details={"error": str(exc)},
                )
                self._emit_progress(f"⚠ LLM не смогла принять решение: {exc}")
                break

            decision_failures = 0
            state.variables.setdefault("loop_decisions", []).append(
                decision.model_dump(mode="json")
            )
            self._emit_think_progress(decision, state, agent_spec)
            self._emit_decision_progress(decision, state, agent_spec)
            self._refresh_context(state, agent_spec)

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
            self._persist_loop_progress(
                state, executed_signatures, repeat_notes, repeat_count
            )

        if state.status == AgentRunStatus.RUNNING:
            state.mark_failed("Достигнут лимит шагов без завершения цели")

        self._persist_loop_progress(
            state, executed_signatures, repeat_notes, repeat_count
        )
        self._refresh_context(state, agent_spec)
        self._add_terminal_event(state)
        self._refresh_context(state, agent_spec)
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
            state.variables["human_plan_ahead"] = decision.reason
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
            self._refresh_context(state, agent_spec)
            return True

        if decision_type == SupervisorDecisionType.REQUEST_CREDENTIALS:
            state.variables["human_plan_ahead"] = decision.reason
            state.pause_for_credentials(decision.reason)
            self._add_run_event(
                state,
                AgentRunEventType.HUMAN_APPROVAL_REQUESTED,
                "Агент ожидает credentials вне LLM-контекста",
                details={"reason": decision.reason},
            )
            self._refresh_context(state, agent_spec)
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
        is_vision_tool = proposal.tool_name in VISION_INTERACTION_TOOLS
        # Паузу (agent.wait) можно повторять — например, периодически ждать
        # письмо/код. Дедупликация по сигнатуре её не блокирует.
        allow_repeat = is_vision_tool or proposal.tool_name == WAIT_TOOL_NAME
        if signature in executed_signatures and not allow_repeat:
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

        if not allow_repeat:
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
        # Vision-действие выполнилось, но не изменило страницу — не даём агенту
        # бесконечно повторять одно и то же (например прокрутку без сдвига).
        if is_vision_tool:
            no_progress_note = state.variables.pop("_vision_no_progress_note", None)
            if no_progress_note:
                repeat_notes.append(no_progress_note)
                self._emit_progress(f"↺ {no_progress_note}")
                return "repeat"
        return False

    def _prepare_wait_tool(self, tool_name: str, proposed_input: dict) -> None:
        """Показать значок паузы и включить прерывание сна при остановке."""
        if tool_name != WAIT_TOOL_NAME:
            return
        try:
            seconds = float(proposed_input.get("seconds"))
        except (TypeError, ValueError):
            seconds = 0.0
        self._emit_progress(
            f"⏳ Агент делает паузу на {seconds:g} с и продолжит автоматически…"
        )
        try:
            tool = self._tool_registry.get(tool_name)
        except Exception:
            return
        if hasattr(tool, "cancel_check"):
            tool.cancel_check = self._is_cancel_requested

    def _execute_loop_tool(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        tool_name: str,
        proposed_input: dict,
        reason: str,
        human_approved: bool = False,
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
        self._prepare_wait_tool(tool_name, proposed_input)
        result = self._tool_gateway.execute_tool(
            agent_spec=agent_spec,
            run_id=state.run_id,
            tool_name=tool_name,
            input_data=input_data,
            human_approved=human_approved,
        )

        if result.requires_human_approval:
            # Запоминаем инструмент и его параметры, чтобы выполнить его после
            # подтверждения человека, не начиная работу заново.
            state.variables["pending_loop_tool"] = {
                "tool_name": tool_name,
                "input_data": proposed_input,
                "reason": reason,
            }
            state.variables["human_plan_ahead"] = reason
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
            self._refresh_context(state, agent_spec)
            return

        self._record_tool_result(state, input_data, result)
        if result.ok:
            output_data = result.output_data or {}
            if tool_name in VISION_INTERACTION_TOOLS:
                self._track_vision_progress(state, tool_name, proposed_input, output_data)
            stored_output = self._stash_screenshot(state, output_data)
            stored_output = self._stash_page_html(state, stored_output)
            state.variables.setdefault("tool_outputs", {})[tool_name] = stored_output
            self._refresh_context(state, agent_spec)
            output_keys = sorted(output_data.keys())
            self._add_run_event(
                state,
                AgentRunEventType.TOOL_CALL_COMPLETED,
                f"Инструмент {tool_name} выполнен",
                tool_name=tool_name,
                details={"output_keys": output_keys},
            )
            if tool_name == WAIT_TOOL_NAME:
                waited = output_data.get("waited_seconds", 0)
                if output_data.get("cancelled"):
                    self._emit_progress(
                        f"⏳ Пауза прервана после {waited:g} с (остановка агента)."
                    )
                else:
                    self._emit_progress(
                        f"⏳ Пауза {waited:g} с завершена. Продолжаю работу…"
                    )
                return
            self._emit_progress(
                f"✓ Инструмент {tool_name} выполнен. Данные: "
                f"{', '.join(output_keys) if output_keys else 'нет полей'}",
                state,
                agent_spec,
            )
            return

        self._record_tool_result(state, input_data, result)
        if result.output_data is not None:
            state.variables.setdefault("tool_outputs", {})[tool_name] = result.output_data
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
            f"[{result.error_type or 'ERROR'}]: {result.error_message or ''}",
            state,
            agent_spec,
        )
        self._refresh_context(state, agent_spec)

    def _record_tool_result(
        self,
        state: AgentRuntimeState,
        input_data: dict,
        result: ToolCallResult,
    ) -> None:
        """Сохранить результат инструмента и отразить его в контексте."""
        super()._record_tool_result(state, input_data, result)
        try:
            snapshot = self._context_manager.restore_from_state(state)
            if state.tool_results:
                self._context_manager.record_tool_result(snapshot, state.tool_results[-1])
            self._context_manager.save_to_state(state, snapshot)
        except Exception as exc:
            state.variables["context_snapshot_error"] = str(exc)

    def _track_vision_progress(
        self,
        state: AgentRuntimeState,
        tool_name: str,
        proposed_input: dict,
        output_data: dict,
    ) -> None:
        """Определить, изменило ли vision-действие страницу, и подготовить подсказку."""
        signature = _action_signature(tool_name, proposed_input)
        fingerprint = self._vision_fingerprint(output_data)
        store = state.variables.setdefault("vision_fingerprints", {})
        previous = store.get(signature)
        store[signature] = fingerprint

        note: str | None = None
        if "scrolled" in output_data and not output_data.get("scrolled"):
            note = (
                f"browser.scroll не сдвинул область "
                f"(target={output_data.get('scroll_target')}, "
                f"at_bottom={output_data.get('at_bottom')}, "
                f"at_top={output_data.get('at_top')}). Прокрутка в эту сторону/в этой "
                "области больше ничего не даёт — смени направление, укажи x,y другой "
                "прокручиваемой области или заверши сбор данных."
            )
        elif previous is not None and previous == fingerprint:
            note = (
                f"Действие {tool_name} повторно не изменило состояние страницы "
                "(тот же адрес и та же позиция). Не повторяй его — попробуй другое "
                "действие/область или заверши задачу выводом."
            )
        state.variables["_vision_no_progress_note"] = note

    @staticmethod
    def _vision_fingerprint(output_data: dict) -> str:
        """Компактный отпечаток состояния страницы после vision-действия."""
        parts = [
            str(output_data.get("url") or ""),
            str(output_data.get("title") or ""),
        ]
        has_scroll_metrics = False
        for key in ("scroll_top", "scroll_left"):
            if key in output_data:
                has_scroll_metrics = True
                parts.append(f"{key}={output_data.get(key)}")
        if not has_scroll_metrics:
            parts.append(
                "shot=" + str(len(str(output_data.get("screenshot_base64") or "")))
            )
        return "|".join(parts)

    def _stash_screenshot(self, state: AgentRuntimeState, output_data: dict) -> dict:
        """Сохранить base64-скриншот отдельно (для image в промпте) и убрать из текста."""
        if not isinstance(output_data, dict) or "screenshot_base64" not in output_data:
            return output_data
        screenshot = str(output_data.get("screenshot_base64") or "")
        if screenshot:
            state.variables["last_screenshot"] = {
                "base64": screenshot,
                "media_type": output_data.get("screenshot_media_type") or "image/png",
                "url": output_data.get("url"),
                "title": output_data.get("title"),
                "viewport_width": output_data.get("viewport_width"),
                "viewport_height": output_data.get("viewport_height"),
            }
        trimmed = {k: v for k, v in output_data.items() if k != "screenshot_base64"}
        trimmed["screenshot_captured"] = bool(screenshot)
        return trimmed

    @staticmethod
    def _stash_page_html(state: AgentRuntimeState, output_data: dict) -> dict:
        """Убрать сырой html из tool_outputs; оставить summary/length для LLM-контекста."""
        if not isinstance(output_data, dict) or "html" not in output_data:
            return output_data
        html = str(output_data.get("html") or "")
        html_summary = str(output_data.get("html_summary") or html[:4000])
        html_length = int(output_data.get("html_length") or len(html))
        truncated = bool(output_data.get("truncated"))
        if html:
            state.variables["last_page_html"] = {
                "url": output_data.get("url"),
                "title": output_data.get("title"),
                "html": html,
                "html_length": html_length,
                "truncated": truncated,
                "html_summary": html_summary,
            }
        trimmed = {k: v for k, v in output_data.items() if k != "html"}
        trimmed["html_captured"] = bool(html)
        trimmed["html_length"] = html_length
        trimmed["truncated"] = truncated
        trimmed["html_summary"] = html_summary
        return trimmed

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
