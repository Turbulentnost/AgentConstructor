"""Простой исполнитель AgentSpec как графа шагов."""

from __future__ import annotations

from uuid import uuid4

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
    ) -> None:
        """Создать runtime с gateway и необязательными репозиториями."""
        self._tool_gateway = tool_gateway
        self._run_repository = run_repository
        self._audit_repository = audit_repository

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

        if not approved:
            state.resume_after_human("Отклонить", comment)
            if pending_tool_node_id is not None:
                state.variables.pop("pending_tool_node_id", None)
                node = agent_spec.get_node(pending_tool_node_id)
                if node.next_on_error is not None:
                    self._move_to_next_node(state, node.next_on_error)
                    self._save_checkpoint(state)
                    return self._continue_execution(agent_spec, state)
            state.mark_cancelled("Пользователь отклонил действие")
            self._save_checkpoint(state)
            return state

        state.resume_after_human("Подтвердить", comment)
        if pending_tool_node_id is None:
            state.mark_failed("Не найден узел инструмента для продолжения")
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
            return state
        return self._continue_execution(agent_spec, state)

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
                self._save_checkpoint(state)
                return state

            state.step_counter += 1
            self._execute_node(agent_spec, state, node)
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
            return

        self._record_tool_result(state, input_data, result)
        if result.ok:
            if result.output_data is not None:
                tool_outputs = state.variables.setdefault("tool_outputs", {})
                tool_outputs[node.tool_name] = result.output_data
            self._move_to_next_node(state, node.next_on_success)
            return

        state.add_error(result.error_message or result.error_type or "Ошибка инструмента")
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
