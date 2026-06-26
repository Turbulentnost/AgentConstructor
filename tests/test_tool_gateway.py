"""Тесты безопасного вызова инструментов через ToolGateway."""

from typing import Any

import pytest

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.fake_tools import (
    FakeDangerousTool,
    FakeDraftTool,
    FakeReadTool,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def make_goal() -> AgentGoal:
    """Создать цель агента для gateway-тестов."""
    return AgentGoal(
        main_goal="Проверить вызов инструмента",
        success_criteria=["Инструмент безопасно обработан"],
        forbidden_actions=["Не обходить ToolGateway"],
    )


def make_final_node() -> AgentGraphNode:
    """Создать минимальный final-узел для AgentSpec."""
    return AgentGraphNode(
        node_id="final",
        node_type=AgentGraphNodeType.FINAL,
        title="Завершить",
        description="Завершить тестовый граф",
        tool_name=None,
        next_on_success=None,
        next_on_error=None,
        requires_human_approval=False,
    )


def make_permission(
    tool_name: str,
    action_level: AgentActionLevel,
    *,
    requires_human_approval: bool = False,
    allowed: bool = True,
) -> AgentToolPermission:
    """Создать разрешение инструмента для AgentSpec."""
    return AgentToolPermission(
        tool_name=tool_name,
        action_level=action_level,
        requires_human_approval=requires_human_approval,
        allowed=allowed,
    )


def make_agent_spec(
    permissions: list[AgentToolPermission],
) -> AgentSpec:
    """Создать минимальную спецификацию агента с указанными tools."""
    return AgentSpec(
        agent_id="gateway-test-agent",
        name="Gateway Test Agent",
        description="Агент для проверки ToolGateway",
        goal=make_goal(),
        data_requirements=[],
        tools=permissions,
        graph_nodes=[make_final_node()],
        runtime_limits=AgentRuntimeLimits(),
    )


def make_registry(*tools: BaseTool) -> ToolRegistry:
    """Создать реестр и зарегистрировать переданные инструменты."""
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


class CountingReadTool(FakeReadTool):
    """Fake read-инструмент со счетчиком вызовов execute."""

    def __init__(self) -> None:
        """Создать инструмент со счетчиком."""
        super().__init__()
        self.execute_count = 0

    def execute(self, input_data: dict) -> ToolCallResult:
        """Увеличить счетчик и выполнить fake read."""
        self.execute_count += 1
        return super().execute(input_data)


class CountingDangerousTool(FakeDangerousTool):
    """Fake dangerous-инструмент со счетчиком вызовов execute."""

    def __init__(self) -> None:
        """Создать dangerous-инструмент со счетчиком."""
        super().__init__()
        self.execute_count = 0

    def execute(self, input_data: dict) -> ToolCallResult:
        """Увеличить счетчик и выполнить fake dangerous."""
        self.execute_count += 1
        return super().execute(input_data)


class CountingWriteTool(BaseTool):
    """Fake write-инструмент со счетчиком вызовов execute."""

    def __init__(self) -> None:
        """Создать write-инструмент."""
        super().__init__(
            ToolDefinition(
                name="fake.write",
                title="Fake Write",
                description="Имитирует изменение данных.",
                side_effect_level=ToolSideEffectLevel.WRITE,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={},
                output_schema={},
            )
        )
        self.execute_count = 0

    def execute(self, input_data: dict) -> ToolCallResult:
        """Увеличить счетчик и вернуть успешный write-результат."""
        self.execute_count += 1
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"written": True},
        )


class FailingTool(FakeReadTool):
    """Fake-инструмент, выбрасывающий исключение при execute."""

    def execute(self, input_data: dict) -> ToolCallResult:
        """Выбросить тестовую ошибку исполнения."""
        raise RuntimeError("boom")


class ErrorResultTool(FakeReadTool):
    """Fake-инструмент, возвращающий ошибочный ToolCallResult без исключения."""

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть контролируемую ошибку инструмента."""
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type="FAKE_TOOL_ERROR",
            error_message="fake tool failed",
        )


class InvalidResultTool(FakeReadTool):
    """Fake-инструмент, возвращающий некорректный результат."""

    def execute(self, input_data: dict) -> Any:
        """Вернуть объект, который не является ToolCallResult."""
        return {"bad": True}


def test_allowed_read_tool_executes_without_human_approval() -> None:
    """Разрешенный read tool выполняется без human_approved."""
    registry = make_registry(FakeReadTool())
    gateway = ToolGateway(registry)
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.ok is True
    assert result.output_data == {"value": "fake_read_result"}


def test_create_draft_tool_executes_without_human_approval() -> None:
    """create_draft tool выполняется без human_approved."""
    registry = make_registry(FakeDraftTool())
    gateway = ToolGateway(registry)
    agent_spec = make_agent_spec([
        make_permission("fake.create_draft", AgentActionLevel.CREATE_DRAFT),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.create_draft", {})

    assert result.ok is True
    assert result.output_data == {"draft_id": "draft-1"}


def test_dangerous_tool_without_human_approval_does_not_execute() -> None:
    """dangerous tool без human_approved не выполняется."""
    tool = CountingDangerousTool()
    registry = make_registry(tool)
    gateway = ToolGateway(registry)
    agent_spec = make_agent_spec([
        make_permission(
            "fake.dangerous",
            AgentActionLevel.DANGEROUS,
            requires_human_approval=True,
        ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.dangerous", {})

    assert result.ok is False
    assert result.error_type == "HUMAN_APPROVAL_REQUIRED"
    assert tool.execute_count == 0


def test_dangerous_tool_without_human_approval_returns_approval_flag() -> None:
    """dangerous tool без human_approved возвращает requires_human_approval=True."""
    registry = make_registry(FakeDangerousTool())
    gateway = ToolGateway(registry)
    agent_spec = make_agent_spec([
        make_permission(
            "fake.dangerous",
            AgentActionLevel.DANGEROUS,
            requires_human_approval=True,
        ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.dangerous", {})

    assert result.requires_human_approval is True


def test_dangerous_tool_with_human_approval_executes() -> None:
    """dangerous tool с human_approved=True выполняется."""
    registry = make_registry(FakeDangerousTool())
    gateway = ToolGateway(registry)
    agent_spec = make_agent_spec([
        make_permission(
            "fake.dangerous",
            AgentActionLevel.DANGEROUS,
            requires_human_approval=True,
        ),
    ])

    result = gateway.execute_tool(
        agent_spec,
        "run-1",
        "fake.dangerous",
        {},
        human_approved=True,
    )

    assert result.ok is True
    assert result.output_data == {"done": True}


def test_write_tool_without_human_approval_does_not_execute() -> None:
    """write tool без human_approved не выполняется."""
    tool = CountingWriteTool()
    registry = make_registry(tool)
    gateway = ToolGateway(registry)
    agent_spec = make_agent_spec([
        make_permission("fake.write", AgentActionLevel.WRITE),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.write", {})

    assert result.error_type == "HUMAN_APPROVAL_REQUIRED"
    assert tool.execute_count == 0


def test_unregistered_tool_returns_tool_not_found() -> None:
    """Инструмент, которого нет в registry, возвращает TOOL_NOT_FOUND."""
    gateway = ToolGateway(make_registry())
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.error_type == "TOOL_NOT_FOUND"


def test_tool_missing_in_agent_spec_returns_not_allowed() -> None:
    """Инструмент вне agent_spec.tools возвращает TOOL_NOT_ALLOWED_FOR_AGENT."""
    gateway = ToolGateway(make_registry(FakeReadTool()))
    agent_spec = make_agent_spec([])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.error_type == "TOOL_NOT_ALLOWED_FOR_AGENT"


def test_disabled_tool_returns_disabled_for_agent() -> None:
    """Инструмент с allowed=False возвращает TOOL_DISABLED_FOR_AGENT."""
    gateway = ToolGateway(make_registry(FakeReadTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ, allowed=False),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.error_type == "TOOL_DISABLED_FOR_AGENT"


def test_empty_run_id_returns_invalid_run_id() -> None:
    """Пустой run_id возвращает INVALID_RUN_ID."""
    gateway = ToolGateway(make_registry(FakeReadTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "", "fake.read", {})

    assert result.error_type == "INVALID_RUN_ID"
    assert result.error_message == "run_id не должен быть пустым"


def test_empty_tool_name_returns_invalid_tool_name() -> None:
    """Пустой tool_name возвращает INVALID_TOOL_NAME."""
    gateway = ToolGateway(make_registry(FakeReadTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "", {})

    assert result.tool_name == "unknown"
    assert result.error_type == "INVALID_TOOL_NAME"


def test_tool_exception_returns_tool_execution_error() -> None:
    """Исключение внутри tool.execute возвращается как TOOL_EXECUTION_ERROR."""
    gateway = ToolGateway(make_registry(FailingTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.ok is False
    assert result.error_type == "TOOL_EXECUTION_ERROR"
    assert result.error_message == "boom"


def test_tool_error_result_is_returned_without_raising() -> None:
    """Ошибочный ToolCallResult от инструмента возвращается без падения gateway."""
    gateway = ToolGateway(make_registry(ErrorResultTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.ok is False
    assert result.error_type == "FAKE_TOOL_ERROR"
    assert result.error_message == "fake tool failed"


def test_execute_not_called_when_human_approval_required() -> None:
    """tool.execute не вызывается, если требуется HumanApproval."""
    tool = CountingDangerousTool()
    gateway = ToolGateway(make_registry(tool))
    agent_spec = make_agent_spec([
        make_permission(
            "fake.dangerous",
            AgentActionLevel.DANGEROUS,
            requires_human_approval=True,
        ),
    ])

    gateway.execute_tool(agent_spec, "run-1", "fake.dangerous", {})

    assert tool.execute_count == 0


def test_execute_not_called_when_tool_disabled_for_agent() -> None:
    """tool.execute не вызывается, если инструмент запрещен AgentSpec."""
    tool = CountingReadTool()
    gateway = ToolGateway(make_registry(tool))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ, allowed=False),
    ])

    gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert tool.execute_count == 0


def test_gateway_does_not_raise_on_common_errors() -> None:
    """Gateway не выбрасывает наружу исключения при обычных ошибках."""
    gateway = ToolGateway(make_registry(FailingTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    results = [
        gateway.execute_tool(agent_spec, "", "fake.read", {}),
        gateway.execute_tool(agent_spec, "run-1", "", {}),
        gateway.execute_tool(agent_spec, "run-1", "unknown", {}),
        gateway.execute_tool(agent_spec, "run-1", "fake.read", {}),
    ]

    assert all(result.ok is False for result in results)


def test_invalid_tool_result_returns_invalid_tool_result() -> None:
    """Некорректный результат execute возвращает INVALID_TOOL_RESULT."""
    gateway = ToolGateway(make_registry(InvalidResultTool()))
    agent_spec = make_agent_spec([
        make_permission("fake.read", AgentActionLevel.READ),
    ])

    result = gateway.execute_tool(agent_spec, "run-1", "fake.read", {})

    assert result.error_type == "INVALID_TOOL_RESULT"
