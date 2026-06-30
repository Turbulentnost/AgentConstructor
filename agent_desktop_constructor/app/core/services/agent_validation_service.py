"""Сервис пробной проверки AgentSpec перед сохранением/запуском."""

from __future__ import annotations

from agent_desktop_constructor.app.core.models.agent_validation import (
    AgentValidationResult,
    AgentValidationStatus,
)
from agent_desktop_constructor.core.models.agent_spec import AgentActionLevel, AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.catalog import (
    ToolsCatalog,
    validate_agent_spec_tools_against_catalog,
)
from agent_desktop_constructor.tools.registry import ToolRegistry


class AgentValidationService:
    """Валидирует AgentSpec и выполняет read-only пробный запуск."""

    def __init__(
        self,
        agent_service: object | None,
        runtime: SimpleAgentRuntime,
        tool_registry: ToolRegistry,
        tools_catalog: ToolsCatalog,
    ) -> None:
        """Сохранить зависимости без прямого доступа к инструментам."""
        self._agent_service = agent_service
        self._runtime = runtime
        self._tool_registry = tool_registry
        self._tools_catalog = tools_catalog
        self._validation_states: dict[str, AgentRuntimeState] = {}

    def validate_agent(
        self,
        agent_spec: AgentSpec,
        user_request: str,
    ) -> AgentValidationResult:
        """Проверить AgentSpec и выполнить пробный запуск."""
        errors = self._validate_agent_can_run(agent_spec)
        if errors:
            return AgentValidationResult(
                agent_id=agent_spec.agent_id,
                status=AgentValidationStatus.FAILED,
                run_id=None,
                errors=errors,
                warnings=[],
                summary="AgentSpec не прошёл проверку инструментов.",
                suggested_fixes=["Проверьте ToolsCatalog, ToolRegistry и graph_nodes."],
            )

        state = self._runtime.run(
            agent_spec,
            initial_variables={
                "user_request": user_request,
                "validation_mode": True,
                "read_only_trial_run": True,
            },
        )
        self._validation_states[state.run_id] = state
        status = self._status_from_runtime_state(state)
        errors = self._errors_from_state(state, status)
        warnings = list(state.variables.get("supervisor_warnings", []))
        output_data = self._extract_output_data(state)
        final_message = self._extract_final_message(state, output_data)
        return AgentValidationResult(
            agent_id=agent_spec.agent_id,
            status=status,
            run_id=state.run_id,
            errors=errors,
            warnings=warnings,
            summary=self._summary_from_status(status, state),
            final_message=final_message,
            output_data=output_data,
            suggested_fixes=self._suggest_fixes(status, errors, warnings),
        )

    def get_validation_state(self, run_id: str | None) -> AgentRuntimeState | None:
        """Вернуть состояние пробного запуска по run_id."""
        if run_id is None:
            return None
        return self._validation_states.get(run_id)

    def _validate_agent_can_run(self, agent_spec: AgentSpec) -> list[str]:
        """Проверить, что все tools известны каталогу и зарегистрированы."""
        errors: list[str] = []
        try:
            validate_agent_spec_tools_against_catalog(agent_spec, self._tools_catalog)
        except ValueError as exc:
            errors.append(str(exc))

        for tool_name in sorted(agent_spec.allowed_tool_names()):
            if not self._tool_registry.has_tool(tool_name):
                errors.append(f"Инструмент {tool_name!r} не зарегистрирован")
        for node in agent_spec.graph_nodes:
            if node.tool_name is not None and not self._tool_registry.has_tool(
                node.tool_name
            ):
                errors.append(
                    f"Инструмент узла {node.node_id!r} не зарегистрирован: "
                    f"{node.tool_name!r}"
                )
        for permission in agent_spec.tools:
            if not self._tool_registry.has_tool(permission.tool_name):
                continue
            definition = self._tool_registry.get(permission.tool_name).definition
            risky_tool = definition.side_effect_level in {
                ToolSideEffectLevel.WRITE,
                ToolSideEffectLevel.DANGEROUS,
            }
            risky_permission = permission.action_level in {
                AgentActionLevel.WRITE,
                AgentActionLevel.DANGEROUS,
            }
            if (risky_tool or risky_permission) and not (
                definition.requires_human_approval
                or permission.requires_human_approval
            ):
                errors.append(
                    f"Инструмент {permission.tool_name!r} write/dangerous "
                    "должен требовать HumanApproval"
                )
        return errors

    def _status_from_runtime_state(
        self,
        state: AgentRuntimeState,
    ) -> AgentValidationStatus:
        """Преобразовать Runtime status в validation status."""
        if state.status == AgentRunStatus.PAUSED_FOR_HUMAN:
            return AgentValidationStatus.NEEDS_HUMAN
        if state.status == AgentRunStatus.PAUSED_FOR_CREDENTIALS:
            return AgentValidationStatus.NEEDS_CREDENTIALS
        if self._has_credential_error(state):
            return AgentValidationStatus.NEEDS_CREDENTIALS
        if state.status == AgentRunStatus.COMPLETED and self._has_useful_result(state):
            return AgentValidationStatus.PASSED
        return AgentValidationStatus.FAILED

    def _summary_from_status(
        self,
        status: AgentValidationStatus,
        state: AgentRuntimeState,
    ) -> str:
        """Сформировать краткую сводку проверки."""
        if status == AgentValidationStatus.PASSED:
            return "Пробный запуск завершён успешно."
        if status == AgentValidationStatus.NEEDS_HUMAN:
            return "Пробный запуск остановлен: требуется действие человека."
        if status == AgentValidationStatus.NEEDS_CREDENTIALS:
            return "Пробный запуск остановлен: требуется авторизация/credentials."
        return "Пробный запуск завершился ошибкой."

    def _suggest_fixes(
        self,
        status: AgentValidationStatus,
        errors: list[str],
        warnings: list[str] | None = None,
    ) -> list[str]:
        """Предложить безопасные исправления по результату проверки."""
        if status == AgentValidationStatus.PASSED:
            if warnings:
                return ["Проверка прошла, но проверьте предупреждения LLM Supervisor."]
            return []
        if errors:
            return ["Проверьте граф, разрешения tools и регистрацию ToolRegistry."]
        if status == AgentValidationStatus.NEEDS_CREDENTIALS:
            return ["Подключите credentials вне LLM-контекста и повторите проверку."]
        if status == AgentValidationStatus.NEEDS_HUMAN:
            return ["Подтвердите действие или измените AgentSpec на read-only граф."]
        if warnings:
            return ["Проверьте рекомендации LLM Supervisor и события пробного запуска."]
        return ["Откройте события пробного run_id для диагностики."]

    def _has_useful_result(self, state: AgentRuntimeState) -> bool:
        """Проверить, что completed run дал финальное сообщение или output_data."""
        if state.variables.get("final_message"):
            return True
        if state.variables.get("tool_outputs"):
            return True
        return any(result.ok and bool(result.output_data) for result in state.tool_results)

    def _extract_output_data(self, state: AgentRuntimeState) -> dict | None:
        """Вернуть последнюю полезную структуру результата выполнения."""
        if state.variables.get("final_output") and isinstance(
            state.variables["final_output"],
            dict,
        ):
            return state.variables["final_output"]
        for result in reversed(state.tool_results):
            if result.ok and result.output_data:
                return result.output_data
        tool_outputs = state.variables.get("tool_outputs")
        if isinstance(tool_outputs, dict) and tool_outputs:
            last_key = next(reversed(tool_outputs))
            last_output = tool_outputs.get(last_key)
            if isinstance(last_output, dict):
                return last_output
        return None

    def _extract_final_message(
        self,
        state: AgentRuntimeState,
        output_data: dict | None,
    ) -> str | None:
        """Сформировать человекочитаемый итоговый вывод проверки."""
        final_message = state.variables.get("final_message")
        if isinstance(final_message, str) and final_message.strip():
            return final_message
        if output_data is None:
            return None
        for key in [
            "recommendation_text",
            "report_text",
            "summary_text",
            "summary",
            "text",
            "final_message",
        ]:
            value = output_data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        recommendations = output_data.get("recommendations")
        if isinstance(recommendations, list) and recommendations:
            return "\n".join(str(item) for item in recommendations)
        return None

    def _has_credential_error(self, state: AgentRuntimeState) -> bool:
        """Проверить credential-related ошибки инструментов."""
        credential_error_types = {
            "ONEC_AUTH_REQUIRED",
            "CREDENTIALS_REQUIRED",
            "AUTH_REQUIRED",
            "CREDENTIAL_REQUEST",
        }
        for result in state.tool_results:
            if result.error_type in credential_error_types:
                return True
        return False

    def _errors_from_state(
        self,
        state: AgentRuntimeState,
        status: AgentValidationStatus,
    ) -> list[str]:
        """Собрать ошибки проверки из RuntimeState и tool_results."""
        if status in {
            AgentValidationStatus.PASSED,
            AgentValidationStatus.NEEDS_HUMAN,
            AgentValidationStatus.NEEDS_CREDENTIALS,
        }:
            return list(state.errors)
        errors = list(state.errors)
        for result in state.tool_results:
            if result.ok:
                continue
            message = result.error_message or result.error_type or "Ошибка инструмента"
            errors.append(f"{result.tool_name}: {message}")
        if state.status == AgentRunStatus.COMPLETED and not self._has_useful_result(state):
            errors.append("Пробный запуск завершился без полезного результата")
        return errors

