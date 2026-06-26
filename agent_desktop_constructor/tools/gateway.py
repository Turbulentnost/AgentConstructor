"""Безопасная точка вызова инструментов агента."""

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.registry import ToolRegistry


class ToolGateway:
    """Единая точка проверки безопасности и вызова одного инструмента."""

    def __init__(self, registry: ToolRegistry) -> None:
        """Создать gateway поверх каталога зарегистрированных инструментов."""
        self._registry = registry

    def execute_tool(
        self,
        agent_spec: AgentSpec,
        run_id: str,
        tool_name: str,
        input_data: dict,
        human_approved: bool = False,
    ) -> ToolCallResult:
        """Проверить права и безопасно выполнить один инструмент."""
        if not run_id.strip():
            return self._error_result(
                tool_name=tool_name or "unknown",
                error_type="INVALID_RUN_ID",
                error_message="run_id не должен быть пустым",
            )

        if not tool_name.strip():
            return self._error_result(
                tool_name="unknown",
                error_type="INVALID_TOOL_NAME",
                error_message="tool_name не должен быть пустым",
            )

        if not self._registry.has_tool(tool_name):
            return self._error_result(
                tool_name=tool_name,
                error_type="TOOL_NOT_FOUND",
                error_message="Инструмент не зарегистрирован",
            )

        permission = self._find_agent_tool_permission(agent_spec, tool_name)
        if permission is None:
            return self._error_result(
                tool_name=tool_name,
                error_type="TOOL_NOT_ALLOWED_FOR_AGENT",
                error_message="Инструмент не разрешён для этого агента",
            )

        if not permission.allowed:
            return self._error_result(
                tool_name=tool_name,
                error_type="TOOL_DISABLED_FOR_AGENT",
                error_message="Инструмент отключён для этого агента",
            )

        tool = self._registry.get(tool_name)
        if self._is_human_approval_required(tool.definition, permission):
            if not human_approved:
                return self._approval_required_result(tool_name)

        try:
            result = tool.execute(input_data)
        except Exception as exc:
            return self._error_result(
                tool_name=tool_name,
                error_type="TOOL_EXECUTION_ERROR",
                error_message=str(exc),
            )

        if not isinstance(result, ToolCallResult):
            return self._error_result(
                tool_name=tool_name,
                error_type="INVALID_TOOL_RESULT",
                error_message="Инструмент вернул некорректный результат",
            )

        return result

    def _find_agent_tool_permission(
        self,
        agent_spec: AgentSpec,
        tool_name: str,
    ) -> AgentToolPermission | None:
        """Найти разрешение инструмента в AgentSpec."""
        for permission in agent_spec.tools:
            if permission.tool_name == tool_name:
                return permission
        return None

    def _is_human_approval_required(
        self,
        tool_definition: ToolDefinition,
        permission: AgentToolPermission,
    ) -> bool:
        """Определить, требует ли вызов HumanApproval."""
        return (
            tool_definition.requires_human_approval
            or permission.requires_human_approval
            or tool_definition.side_effect_level == ToolSideEffectLevel.DANGEROUS
            or permission.action_level == AgentActionLevel.DANGEROUS
            or tool_definition.side_effect_level == ToolSideEffectLevel.WRITE
            or permission.action_level == AgentActionLevel.WRITE
        )

    def _approval_required_result(self, tool_name: str) -> ToolCallResult:
        """Вернуть результат, сигнализирующий Runtime о необходимости HumanApproval."""
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            output_data=None,
            error_type="HUMAN_APPROVAL_REQUIRED",
            error_message="Для выполнения инструмента требуется подтверждение человека",
            requires_human_approval=True,
        )

    def _error_result(
        self,
        tool_name: str,
        error_type: str,
        error_message: str,
    ) -> ToolCallResult:
        """Вернуть ошибку gateway как ToolCallResult."""
        return ToolCallResult(
            ok=False,
            tool_name=tool_name,
            error_type=error_type,
            error_message=error_message,
        )
