"""Простой исполнитель AgentSpec как графа шагов."""

from __future__ import annotations

from uuid import uuid4

from agent_desktop_constructor.app.core.models.human_approval import (
    HumanApprovalRecord,
    HumanApprovalStatus,
)
from agent_desktop_constructor.app.core.models.run_events import (
    AgentRunEvent,
    AgentRunEventType,
)
from agent_desktop_constructor.core.models.agent_spec import (
    AgentGraphNode,
    AgentGraphNodeType,
    AgentSpec,
)
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    HumanApprovalRequest,
)
from agent_desktop_constructor.core.models.tooling import ToolCallResult
from agent_desktop_constructor.tools.gateway import ToolGateway


class SimpleAgentRuntime:
    """Первый runtime, исполняющий AgentSpec через ToolGateway без LangGraph."""

    def __init__(
        self,
        tool_gateway: ToolGateway,
        run_repository: object | None = None,
        audit_repository: object | None = None,
        run_event_repository: object | None = None,
        human_approval_repository: object | None = None,
    ) -> None:
        """Создать runtime с gateway и необязательными репозиториями."""
        self._tool_gateway = tool_gateway
        self._run_repository = run_repository
        self._audit_repository = audit_repository
        self._run_event_repository = run_event_repository
        self._human_approval_repository = human_approval_repository
        self._terminal_events_emitted: set[str] = set()

    def run(
        self,
        agent_spec: AgentSpec,
        initial_variables: dict | None = None,
        run_id: str | None = None,
    ) -> AgentRuntimeState:
        """Создать состояние запуска и исполнять AgentSpec до остановки."""
        state = AgentRuntimeState(
            run_id=run_id or str(uuid4()),
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.RUNNING,
            current_node_id=agent_spec.get_start_node().node_id,
            variables=initial_variables or {},
        )
        self._create_run(agent_spec, state)
        self._add_run_event(
            state,
            AgentRunEventType.RUN_STARTED,
            "Запуск агента начат",
            details={"agent_id": agent_spec.agent_id},
        )
        return self._continue_execution(agent_spec, state)

    def resume(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        approved: bool,
        comment: str | None = None,
    ) -> AgentRuntimeState:
        """Продолжить запуск после решения человека."""
        if state.status != AgentRunStatus.PAUSED_FOR_HUMAN:
            raise ValueError("Продолжить можно только запуск в статусе paused_for_human")
        if state.pending_human_approval is None:
            raise ValueError("Нет ожидающего HumanApproval-запроса")

        pending_tool_node_id = state.variables.get("pending_tool_node_id")
        approval_node_id = state.pending_human_approval.node_id
        approval_tool_name = state.pending_human_approval.tool_name
        approval_id = state.pending_human_approval.approval_id

        if not approved:
            self._answer_human_approval_record(
                approval_id,
                HumanApprovalStatus.REJECTED,
                "Отклонить",
                comment,
            )
            state.resume_after_human("Отклонить", comment)
            self._add_run_event(
                state,
                AgentRunEventType.HUMAN_APPROVAL_ANSWERED,
                "Получено решение человека",
                node_id=approval_node_id,
                tool_name=approval_tool_name,
                details={
                    "approval_id": approval_id,
                    "approved": False,
                    "comment": comment,
                },
            )
            if pending_tool_node_id is not None:
                state.variables.pop("pending_tool_node_id", None)
                node = agent_spec.get_node(pending_tool_node_id)
                if node.next_on_error is not None:
                    self._move_to_next_node(state, node.next_on_error)
                    self._save_checkpoint(state)
                    return self._continue_execution(agent_spec, state)
            node = agent_spec.get_node(approval_node_id)
            if node.next_on_error is not None:
                self._move_to_next_node(state, node.next_on_error)
                self._save_checkpoint(state)
                return self._continue_execution(agent_spec, state)
            state.mark_cancelled("Пользователь отклонил действие")
            self._add_terminal_event(state)
            self._save_checkpoint(state)
            return state

        self._answer_human_approval_record(
            approval_id,
            HumanApprovalStatus.APPROVED,
            "Подтвердить",
            comment,
        )
        state.resume_after_human("Подтвердить", comment)
        self._add_run_event(
            state,
            AgentRunEventType.HUMAN_APPROVAL_ANSWERED,
            "Получено решение человека",
            node_id=approval_node_id,
            tool_name=approval_tool_name,
            details={"approval_id": approval_id, "approved": True, "comment": comment},
        )
        if pending_tool_node_id is None:
            node = agent_spec.get_node(approval_node_id)
            if node.next_on_success is not None:
                self._move_to_next_node(state, node.next_on_success)
                self._save_checkpoint(state)
                result_state = self._continue_execution(agent_spec, state)
                self._add_terminal_event(result_state)
                return result_state
            state.mark_failed("Не найден следующий узел для продолжения")
            self._add_terminal_event(state)
            self._save_checkpoint(state)
            return state

        state.variables.pop("pending_tool_node_id", None)
        node = agent_spec.get_node(pending_tool_node_id)
        self._execute_tool_node(agent_spec, state, node, human_approved=True)
        self._save_checkpoint(state)
        if state.status in {
            AgentRunStatus.PAUSED_FOR_HUMAN,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }:
            self._add_terminal_event(state)
            return state
        result_state = self._continue_execution(agent_spec, state)
        self._add_terminal_event(result_state)
        return result_state

    def _continue_execution(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
    ) -> AgentRuntimeState:
        """Продолжить исполнение графа от текущего узла."""
        limits = agent_spec.runtime_limits
        while state.can_continue(limits.max_steps, limits.max_tool_calls):
            if state.current_node_id is None:
                state.mark_failed("Не указан текущий узел")
                self._save_checkpoint(state)
                return state

            try:
                node = agent_spec.get_node(state.current_node_id)
            except ValueError as exc:
                state.mark_failed(str(exc))
                self._add_run_event(
                    state,
                    AgentRunEventType.NODE_FAILED,
                    f"Ошибка выполнения узла {state.current_node_id}",
                    node_id=state.current_node_id,
                    details={"error": str(exc)},
                )
                self._add_terminal_event(state)
                self._save_checkpoint(state)
                return state

            self._add_run_event(
                state,
                AgentRunEventType.NODE_STARTED,
                f"Начато выполнение узла {node.node_id}",
                node_id=node.node_id,
                tool_name=node.tool_name,
                details={"node_type": node.node_type.value},
            )
            errors_before = len(state.errors)
            state.step_counter += 1
            self._execute_node(agent_spec, state, node)
            if state.status == AgentRunStatus.FAILED or len(state.errors) > errors_before:
                self._add_run_event(
                    state,
                    AgentRunEventType.NODE_FAILED,
                    f"Ошибка выполнения узла {node.node_id}",
                    node_id=node.node_id,
                    tool_name=node.tool_name,
                )
            else:
                self._add_run_event(
                    state,
                    AgentRunEventType.NODE_COMPLETED,
                    f"Узел {node.node_id} выполнен",
                    node_id=node.node_id,
                    tool_name=node.tool_name,
                )
            self._add_terminal_event(state)
            self._save_checkpoint(state)

            if state.status in {
                AgentRunStatus.PAUSED_FOR_HUMAN,
                AgentRunStatus.COMPLETED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            }:
                return state

        if state.status in {AgentRunStatus.CREATED, AgentRunStatus.RUNNING}:
            if state.pending_human_approval is not None:
                state.status = AgentRunStatus.PAUSED_FOR_HUMAN
            elif state.step_counter >= limits.max_steps:
                state.mark_failed("Превышен лимит шагов выполнения")
            elif state.tool_call_counter >= limits.max_tool_calls:
                state.mark_failed("Превышен лимит вызовов инструментов")
            self._add_terminal_event(state)
            self._save_checkpoint(state)

        return state

    def _execute_node(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        node: AgentGraphNode,
    ) -> None:
        """Исполнить один узел графа."""
        if node.node_type == AgentGraphNodeType.VALIDATION:
            state.variables["last_validation_node"] = node.node_id
            self._move_to_next_node(state, node.next_on_success)
            return

        if node.node_type == AgentGraphNodeType.PLANNING:
            state.variables["last_planning_node"] = node.node_id
            self._move_to_next_node(state, node.next_on_success)
            return

        if node.node_type == AgentGraphNodeType.DATA_SEARCH:
            state.variables["last_data_search_node"] = node.node_id
            self._move_to_next_node(state, node.next_on_success)
            return

        if node.node_type == AgentGraphNodeType.ANALYSIS:
            state.variables["last_analysis_node"] = node.node_id
            if node.node_id == "extract_task_candidates":
                state.variables["task_candidates_extracted"] = True
            self._move_to_next_node(state, node.next_on_success)
            return

        if node.node_type == AgentGraphNodeType.ROUTING:
            state.variables["last_routing_node"] = node.node_id
            if node.node_id == "analyze_confidence":
                state.variables["confidence"] = 0.8
            self._move_to_next_node(state, node.next_on_success)
            return

        if node.node_type == AgentGraphNodeType.HUMAN_REVIEW:
            if state.variables.get("force_human_review") is True:
                state.pause_for_human(
                    HumanApprovalRequest(
                        approval_id=str(uuid4()),
                        node_id=node.node_id,
                        tool_name=node.tool_name,
                        question="Агенту требуется проверка человека. Продолжить?",
                        options=["Подтвердить", "Отклонить"],
                        status="pending",
                    )
                )
                self._persist_human_approval_request(state)
                return
            self._move_to_next_node(state, node.next_on_success)
            return

        if node.node_type == AgentGraphNodeType.TOOL_CALL:
            self._execute_tool_node(agent_spec, state, node)
            return

        if node.node_type == AgentGraphNodeType.FINAL:
            if node.node_id == "final_failed":
                state.mark_failed("Агент завершил работу с ошибкой")
            else:
                state.mark_completed()
            return

        state.mark_failed(f"Неизвестный тип узла: {node.node_type}")

    def _execute_tool_node(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        node: AgentGraphNode,
        human_approved: bool = False,
    ) -> None:
        """Выполнить tool_call-узел через ToolGateway."""
        if node.tool_name is None:
            state.mark_failed("У tool_call-узла не указан tool_name")
            return

        self._add_run_event(
            state,
            AgentRunEventType.TOOL_CALL_STARTED,
            f"Вызов инструмента {node.tool_name}",
            node_id=node.node_id,
            tool_name=node.tool_name,
        )
        input_data = {
            "node_id": node.node_id,
            "variables": state.variables,
        }
        result = self._tool_gateway.execute_tool(
            agent_spec=agent_spec,
            run_id=state.run_id,
            tool_name=node.tool_name,
            input_data=input_data,
            human_approved=human_approved,
        )

        if result.requires_human_approval:
            state.variables["pending_tool_node_id"] = node.node_id
            state.pause_for_human(
                HumanApprovalRequest(
                    approval_id=str(uuid4()),
                    node_id=node.node_id,
                    tool_name=node.tool_name,
                    question=(
                        f"Инструмент {node.tool_name} требует подтверждения. "
                        "Выполнить действие?"
                    ),
                    options=["Подтвердить", "Отклонить"],
                    status="pending",
                )
            )
            self._persist_human_approval_request(
                state,
                details={"error_type": result.error_type},
            )
            return

        self._record_tool_result(state, input_data, result)
        if result.ok:
            self._add_run_event(
                state,
                AgentRunEventType.TOOL_CALL_COMPLETED,
                f"Инструмент {node.tool_name} выполнен",
                node_id=node.node_id,
                tool_name=node.tool_name,
                details={"output_keys": sorted((result.output_data or {}).keys())},
            )
            if result.output_data is not None:
                tool_outputs = state.variables.setdefault("tool_outputs", {})
                tool_outputs[node.tool_name] = result.output_data
            self._move_to_next_node(state, node.next_on_success)
            return

        state.add_error(result.error_message or result.error_type or "Ошибка инструмента")
        self._add_run_event(
            state,
            AgentRunEventType.TOOL_CALL_FAILED,
            f"Ошибка инструмента {node.tool_name}",
            node_id=node.node_id,
            tool_name=node.tool_name,
            details={
                "error_type": result.error_type,
                "error_message": result.error_message,
            },
        )
        if node.next_on_error is not None:
            self._move_to_next_node(state, node.next_on_error)
        else:
            state.mark_failed(
                result.error_message
                or f"Инструмент {node.tool_name} завершился с ошибкой"
            )

    def _record_tool_result(
        self,
        state: AgentRuntimeState,
        input_data: dict,
        result: ToolCallResult,
    ) -> None:
        """Сохранить результат вызова ToolGateway в состоянии."""
        state.add_tool_result(
            tool_name=result.tool_name,
            input_data=input_data,
            output_data=result.output_data,
            ok=result.ok,
            error_type=result.error_type,
            error_message=result.error_message,
        )

    def _move_to_next_node(
        self,
        state: AgentRuntimeState,
        next_node_id: str | None,
    ) -> None:
        """Перейти к следующему узлу или зафиксировать ошибку перехода."""
        if next_node_id is None:
            state.mark_failed("Не указан следующий узел")
            return
        state.current_node_id = next_node_id

    def _create_run(self, agent_spec: AgentSpec, state: AgentRuntimeState) -> None:
        """Создать запуск в репозитории, если репозиторий передан."""
        if self._run_repository is None or not hasattr(
            self._run_repository,
            "create_run",
        ):
            return
        try:
            self._run_repository.create_run(agent_spec, state)
        except Exception as exc:
            state.add_error(f"Ошибка создания запуска в хранилище: {exc}")

    def _save_checkpoint(self, state: AgentRuntimeState) -> None:
        """Сохранить checkpoint состояния и audit-событие, если доступны."""
        if self._run_repository is not None and hasattr(
            self._run_repository,
            "save_state",
        ):
            try:
                self._run_repository.save_state(state.run_id, state)
                self._add_run_event(
                    state,
                    AgentRunEventType.CHECKPOINT_SAVED,
                    "Состояние запуска сохранено",
                    details={
                        "status": state.status.value,
                        "current_node_id": state.current_node_id,
                    },
                )
            except Exception as exc:
                state.add_error(f"Ошибка сохранения состояния: {exc}")

        if self._audit_repository is not None and hasattr(
            self._audit_repository,
            "add_log",
        ):
            try:
                self._audit_repository.add_log(
                    action="run.checkpoint_saved",
                    details={
                        "status": state.status.value,
                        "current_node_id": state.current_node_id,
                    },
                    run_id=state.run_id,
                )
            except Exception as exc:
                state.add_error(f"Ошибка записи аудита: {exc}")

    def _add_run_event(
        self,
        state: AgentRuntimeState,
        event_type: AgentRunEventType,
        message: str,
        node_id: str | None = None,
        tool_name: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Сохранить событие выполнения, не роняя Runtime при ошибке."""
        if self._run_event_repository is None or not hasattr(
            self._run_event_repository,
            "add_event",
        ):
            return

        event = AgentRunEvent(
            event_id=str(uuid4()),
            run_id=state.run_id,
            event_type=event_type,
            node_id=node_id,
            tool_name=tool_name,
            message=message,
            details=details or {},
        )
        try:
            self._run_event_repository.add_event(event)
        except Exception as exc:
            state.add_error(f"Ошибка записи события выполнения: {exc}")

    def _persist_human_approval_request(
        self,
        state: AgentRuntimeState,
        details: dict | None = None,
    ) -> None:
        """Сохранить pending-запрос подтверждения и событие ожидания."""
        request = state.pending_human_approval
        if request is None:
            return

        if self._human_approval_repository is not None and hasattr(
            self._human_approval_repository,
            "create_request",
        ):
            record = HumanApprovalRecord(
                approval_id=request.approval_id,
                run_id=state.run_id,
                agent_id=state.agent_id,
                node_id=request.node_id,
                tool_name=request.tool_name,
                question=request.question,
                options=request.options,
                status=HumanApprovalStatus.PENDING,
            )
            try:
                self._human_approval_repository.create_request(record)
            except Exception as exc:
                state.add_error(f"Ошибка сохранения запроса подтверждения: {exc}")

        self._add_run_event(
            state,
            AgentRunEventType.HUMAN_APPROVAL_REQUESTED,
            "Агент ожидает подтверждения человека",
            node_id=request.node_id,
            tool_name=request.tool_name,
            details={"approval_id": request.approval_id, **(details or {})},
        )

    def _answer_human_approval_record(
        self,
        approval_id: str,
        status: HumanApprovalStatus,
        selected_option: str,
        comment: str | None,
    ) -> None:
        """Обновить сохранённый запрос подтверждения, если repository подключён."""
        if self._human_approval_repository is None or not hasattr(
            self._human_approval_repository,
            "answer_request",
        ):
            return
        self._human_approval_repository.answer_request(
            approval_id,
            status,
            selected_option,
            comment,
        )

    def _add_terminal_event(self, state: AgentRuntimeState) -> None:
        """Записать terminal event один раз на run_id."""
        if state.run_id in self._terminal_events_emitted:
            return
        if state.status == AgentRunStatus.COMPLETED:
            self._terminal_events_emitted.add(state.run_id)
            self._add_run_event(
                state,
                AgentRunEventType.RUN_COMPLETED,
                "Запуск агента завершён успешно",
            )
        elif state.status == AgentRunStatus.FAILED:
            self._terminal_events_emitted.add(state.run_id)
            self._add_run_event(
                state,
                AgentRunEventType.RUN_FAILED,
                "Запуск агента завершён с ошибкой",
                details={"errors": list(state.errors)},
            )
        elif state.status == AgentRunStatus.CANCELLED:
            self._terminal_events_emitted.add(state.run_id)
            self._add_run_event(
                state,
                AgentRunEventType.RUN_CANCELLED,
                "Запуск агента отменён",
            )
