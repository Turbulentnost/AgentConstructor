"""Runtime с LLM-supervised циклом после tool_result."""

from __future__ import annotations

from uuid import uuid4

from agent_desktop_constructor.app.core.models.run_events import AgentRunEventType
from agent_desktop_constructor.app.llm.supervisor import LLMSupervisor
from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.core.models.agent_spec import AgentGraphNode, AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    HumanApprovalRequest,
)
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.catalog import ToolsCatalog
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


class SupervisedAgentRuntime(SimpleAgentRuntime):
    """Runtime, который после tool_result спрашивает LLM Supervisor о следующем шаге."""

    def __init__(
        self,
        tool_gateway: ToolGateway,
        llm_supervisor: LLMSupervisor | None = None,
        tools_catalog: ToolsCatalog | None = None,
        tool_registry: ToolRegistry | None = None,
        run_repository: object | None = None,
        audit_repository: object | None = None,
        run_event_repository: object | None = None,
        human_approval_repository: object | None = None,
        credential_request_repository: object | None = None,
    ) -> None:
        """Создать supervised runtime без прямого доступа LLM к инструментам."""
        super().__init__(
            tool_gateway=tool_gateway,
            run_repository=run_repository,
            audit_repository=audit_repository,
            run_event_repository=run_event_repository,
            human_approval_repository=human_approval_repository,
        )
        self._llm_supervisor = llm_supervisor
        self._tools_catalog = tools_catalog
        self._tool_registry = tool_registry
        self._credential_request_repository = credential_request_repository

    def _execute_tool_node(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        node: AgentGraphNode,
        human_approved: bool = False,
    ) -> None:
        """Выполнить tool и после результата применить решение Supervisor."""
        result_count_before = len(state.tool_results)
        super()._execute_tool_node(agent_spec, state, node, human_approved)
        if self._llm_supervisor is None:
            return
        if len(state.tool_results) <= result_count_before:
            return

        self._run_supervisor_loop(agent_spec, state, node)

    def _run_supervisor_loop(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        node: AgentGraphNode,
    ) -> None:
        """Спрашивать Supervisor после каждого tool_result до continue/pause/finish."""
        while state.tool_results and state.can_continue(
            agent_spec.runtime_limits.max_steps,
            agent_spec.runtime_limits.max_tool_calls,
        ):
            latest_tool_result = state.tool_results[-1]
            try:
                decision = self._llm_supervisor.decide(
                    agent_spec=agent_spec,
                    runtime_state=state,
                    latest_event=None,
                    latest_tool_result=latest_tool_result,
                )
            except Exception as exc:
                state.variables.setdefault("supervisor_warnings", []).append(str(exc))
                self._add_run_event(
                    state,
                    AgentRunEventType.NODE_FAILED,
                    "LLM Supervisor не смог принять решение",
                    node_id=node.node_id,
                    tool_name=node.tool_name,
                    details={"error": str(exc)},
                )
                return

            state.variables.setdefault("supervisor_decisions", []).append(
                decision.model_dump(mode="json")
            )
            should_continue_loop = self._apply_supervisor_decision(
                agent_spec,
                state,
                decision,
            )
            if not should_continue_loop:
                return

        if state.status == AgentRunStatus.RUNNING:
            if state.step_counter >= agent_spec.runtime_limits.max_steps:
                state.mark_failed("Превышен лимит шагов выполнения")
            elif state.tool_call_counter >= agent_spec.runtime_limits.max_tool_calls:
                state.mark_failed("Превышен лимит вызовов инструментов")

    def _apply_supervisor_decision(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
    ) -> bool:
        """Безопасно применить SupervisorDecision без прямых tool-вызовов LLM."""
        if decision.decision_type == SupervisorDecisionType.CONTINUE_TO_NEXT:
            return False

        if decision.decision_type == SupervisorDecisionType.FINISH_SUCCESS:
            state.variables["final_message"] = decision.final_message
            state.mark_completed()
            return False

        if decision.decision_type == SupervisorDecisionType.FINISH_FAILED:
            state.mark_failed(decision.reason)
            return False

        if decision.decision_type == SupervisorDecisionType.ASK_HUMAN:
            state.pause_for_human(
                HumanApprovalRequest(
                    approval_id=str(uuid4()),
                    node_id=state.current_node_id or "supervisor",
                    tool_name=None,
                    question=decision.human_question or decision.reason,
                    options=decision.human_options or ["Продолжить", "Остановить"],
                    status="pending",
                )
            )
            self._persist_human_approval_request(
                state,
                details={"source": "llm_supervisor"},
            )
            return False

        if decision.decision_type == SupervisorDecisionType.REQUEST_CREDENTIALS:
            state.pause_for_credentials(decision.reason)
            self._persist_credential_request(state, decision)
            return False

        if decision.decision_type == SupervisorDecisionType.REPLAN_GRAPH:
            state.variables.setdefault("supervisor_warnings", []).append(
                "LLM предложила перестроить граф; автоматическое применение отключено."
            )
            state.variables["proposed_graph_patch"] = decision.graph_patch
            state.pause_for_human(
                HumanApprovalRequest(
                    approval_id=str(uuid4()),
                    node_id=state.current_node_id or "supervisor",
                    tool_name=None,
                    question="LLM Supervisor предлагает перестроить граф. Передать человеку?",
                    options=["Показать предложение", "Отклонить"],
                    status="pending",
                )
            )
            self._persist_human_approval_request(
                state,
                details={"source": "llm_supervisor", "graph_patch": decision.graph_patch},
            )
            return False

        if decision.decision_type == SupervisorDecisionType.RETRY_TOOL:
            self._retry_latest_tool(agent_spec, state, decision)
            return state.status == AgentRunStatus.RUNNING

        if decision.decision_type in {
            SupervisorDecisionType.CALL_TOOL,
            SupervisorDecisionType.CALL_ADDITIONAL_TOOL,
        }:
            self._call_additional_tool(agent_spec, state, decision)
            return state.status == AgentRunStatus.RUNNING

        return False

    def _retry_latest_tool(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
    ) -> None:
        """Повторить последний tool через ToolGateway с лимитом retries."""
        if not state.tool_results:
            state.add_error("Supervisor запросил retry_tool, но tool_results пуст")
            return
        latest = state.tool_results[-1]
        retry_counts = state.variables.setdefault("supervisor_retry_counts", {})
        current_count = int(retry_counts.get(latest.tool_name, 0))
        max_retries = agent_spec.runtime_limits.max_retries_per_tool
        if current_count >= max_retries:
            state.add_error(f"Превышен лимит retry для {latest.tool_name}")
            return
        retry_counts[latest.tool_name] = current_count + 1
        self._execute_supervisor_tool_call(
            agent_spec=agent_spec,
            state=state,
            tool_name=latest.tool_name,
            input_data=latest.input_data,
            reason=decision.reason,
        )

    def _call_additional_tool(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
    ) -> None:
        """Вызвать дополнительный tool только через ToolGateway."""
        if decision.tool_call is None:
            state.add_error("Supervisor не передал tool_call")
            state.mark_failed("Supervisor не передал tool_call")
            return
        self._execute_supervisor_tool_call(
            agent_spec=agent_spec,
            state=state,
            tool_name=decision.tool_call.tool_name,
            input_data=decision.tool_call.input_data,
            reason=decision.tool_call.reason,
        )

    def _execute_supervisor_tool_call(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        tool_name: str,
        input_data: dict,
        reason: str,
    ) -> None:
        """Исполнить предложенный Supervisor tool через ToolGateway."""
        validation_error = self._validate_supervisor_tool_call(agent_spec, tool_name)
        if validation_error is not None:
            state.mark_failed(validation_error)
            self._add_run_event(
                state,
                AgentRunEventType.TOOL_CALL_FAILED,
                f"Supervisor предложил недопустимый инструмент {tool_name}",
                tool_name=tool_name,
                details={"error": validation_error},
            )
            return

        safe_input_data = {
            **input_data,
            "supervisor_reason": reason,
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
            f"Supervisor запросил инструмент {tool_name}",
            tool_name=tool_name,
            details={"reason": reason},
        )
        result = self._tool_gateway.execute_tool(
            agent_spec=agent_spec,
            run_id=state.run_id,
            tool_name=tool_name,
            input_data=safe_input_data,
            human_approved=False,
        )
        self._record_tool_result(state, safe_input_data, result)
        if result.ok:
            state.variables.setdefault("tool_outputs", {})[tool_name] = (
                result.output_data or {}
            )
            self._add_run_event(
                state,
                AgentRunEventType.TOOL_CALL_COMPLETED,
                f"Supervisor tool {tool_name} выполнен",
                tool_name=tool_name,
            )
            return
        if result.requires_human_approval:
            state.pause_for_human(
                HumanApprovalRequest(
                    approval_id=str(uuid4()),
                    node_id=state.current_node_id or "supervisor",
                    tool_name=tool_name,
                    question=f"Supervisor предложил tool {tool_name}. Подтвердить?",
                    options=["Подтвердить", "Отклонить"],
                    status="pending",
                )
            )
            self._persist_human_approval_request(
                state,
                details={"source": "llm_supervisor", "error_type": result.error_type},
            )
            return
        self._add_run_event(
            state,
            AgentRunEventType.TOOL_CALL_FAILED,
            f"Supervisor tool {tool_name} завершился ошибкой",
            tool_name=tool_name,
            details={
                "error_type": result.error_type,
                "error_message": result.error_message,
            },
        )

    def _validate_supervisor_tool_call(
        self,
        agent_spec: AgentSpec,
        tool_name: str,
    ) -> str | None:
        """Проверить tool_call LLM до ToolGateway."""
        if self._tools_catalog is not None and not self._tools_catalog.has_tool(tool_name):
            return f"Инструмент {tool_name!r} отсутствует в ToolsCatalog"
        if self._tool_registry is not None and not self._tool_registry.has_tool(tool_name):
            return f"Инструмент {tool_name!r} не зарегистрирован в ToolRegistry"
        if tool_name not in agent_spec.allowed_tool_names():
            return f"Инструмент {tool_name!r} не разрешён в AgentSpec"
        return None

    def _persist_credential_request(
        self,
        state: AgentRuntimeState,
        decision: SupervisorDecision,
    ) -> None:
        """Сохранить credential request, если соответствующий repository появится."""
        if self._credential_request_repository is not None and hasattr(
            self._credential_request_repository,
            "create_request",
        ):
            self._credential_request_repository.create_request(
                {
                    "run_id": state.run_id,
                    "agent_id": state.agent_id,
                    "reason": decision.reason,
                }
            )
        self._add_run_event(
            state,
            AgentRunEventType.HUMAN_APPROVAL_REQUESTED,
            "Агент ожидает credentials вне LLM-контекста",
            details={"reason": decision.reason},
        )

