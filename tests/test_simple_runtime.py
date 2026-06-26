"""Тесты простого исполнения AgentSpec."""

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


class CountingTool(BaseTool):
    """Тестовый инструмент со счетчиком вызовов."""

    def __init__(
        self,
        name: str = "fake.read",
        side_effect_level: ToolSideEffectLevel = ToolSideEffectLevel.READ,
        requires_human_approval: bool = False,
    ) -> None:
        """Создать инструмент с заданным уровнем риска."""
        super().__init__(
            ToolDefinition(
                name=name,
                title="Counting Tool",
                description="Тестовый инструмент со счетчиком.",
                side_effect_level=side_effect_level,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=requires_human_approval,
                input_schema={},
                output_schema={},
            )
        )
        self.execute_count = 0

    def execute(self, input_data: dict) -> ToolCallResult:
        """Увеличить счетчик и вернуть успешный результат."""
        self.execute_count += 1
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"value": "ok"},
        )


class FailingTool(CountingTool):
    """Тестовый инструмент, возвращающий ошибку."""

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть ошибочный ToolCallResult."""
        self.execute_count += 1
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type="FAKE_ERROR",
            error_message="fake failed",
        )


class CountingGateway(ToolGateway):
    """ToolGateway со счетчиком вызовов execute_tool."""

    def __init__(self, registry: ToolRegistry) -> None:
        """Создать gateway со счетчиком."""
        super().__init__(registry)
        self.call_count = 0

    def execute_tool(self, *args, **kwargs) -> ToolCallResult:
        """Посчитать вызов и делегировать настоящему ToolGateway."""
        self.call_count += 1
        return super().execute_tool(*args, **kwargs)


class FakeRunRepository:
    """Fake repository для проверки checkpoint-сохранений."""

    def __init__(self, fail_on_save: bool = False) -> None:
        """Создать fake repository."""
        self.fail_on_save = fail_on_save
        self.create_run_count = 0
        self.save_state_count = 0

    def create_run(self, agent_spec: AgentSpec, state) -> None:
        """Зафиксировать создание запуска."""
        self.create_run_count += 1

    def save_state(self, run_id: str, state) -> None:
        """Зафиксировать сохранение состояния или выбросить ошибку."""
        self.save_state_count += 1
        if self.fail_on_save:
            raise RuntimeError("storage unavailable")


def make_goal() -> AgentGoal:
    """Создать тестовую цель агента."""
    return AgentGoal(
        main_goal="Выполнить тестовый граф",
        success_criteria=["Граф завершен"],
        forbidden_actions=["Не обходить ToolGateway"],
    )


def node(
    node_id: str,
    node_type: AgentGraphNodeType,
    *,
    tool_name: str | None = None,
    next_on_success: str | None = None,
    next_on_error: str | None = None,
) -> AgentGraphNode:
    """Создать тестовый узел графа."""
    return AgentGraphNode(
        node_id=node_id,
        node_type=node_type,
        title=f"Узел {node_id}",
        description=f"Описание узла {node_id}",
        tool_name=tool_name,
        next_on_success=next_on_success,
        next_on_error=next_on_error,
        requires_human_approval=False,
    )


def permission(
    tool_name: str,
    action_level: AgentActionLevel = AgentActionLevel.READ,
    *,
    requires_human_approval: bool = False,
    allowed: bool = True,
) -> AgentToolPermission:
    """Создать разрешение инструмента."""
    return AgentToolPermission(
        tool_name=tool_name,
        action_level=action_level,
        requires_human_approval=requires_human_approval,
        allowed=allowed,
    )


def make_agent_spec(
    graph_nodes: list[AgentGraphNode],
    tools: list[AgentToolPermission],
    *,
    limits: AgentRuntimeLimits | None = None,
) -> AgentSpec:
    """Создать тестовый AgentSpec."""
    return AgentSpec(
        agent_id="agent-1",
        name="Тестовый агент",
        description="Тестовый агент Runtime",
        goal=make_goal(),
        data_requirements=[],
        tools=tools,
        graph_nodes=graph_nodes,
        runtime_limits=limits or AgentRuntimeLimits(),
    )


def make_gateway(*tools: BaseTool) -> CountingGateway:
    """Создать ToolGateway с зарегистрированными инструментами."""
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return CountingGateway(registry)


def test_runtime_executes_simple_graph_to_completed() -> None:
    """Runtime исполняет простой граф до completed."""
    tool = CountingTool()
    gateway = make_gateway(tool)
    runtime = SimpleAgentRuntime(gateway)
    agent_spec = make_agent_spec(
        [
            node("validate", AgentGraphNodeType.VALIDATION, next_on_success="read"),
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.COMPLETED


def test_runtime_calls_read_tool_through_tool_gateway() -> None:
    """Runtime вызывает read tool через ToolGateway."""
    tool = CountingTool()
    gateway = make_gateway(tool)
    runtime = SimpleAgentRuntime(gateway)
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    runtime.run(agent_spec, run_id="run-1")

    assert gateway.call_count == 1
    assert tool.execute_count == 1


def test_runtime_saves_tool_result_in_state() -> None:
    """Runtime сохраняет результат инструмента в state.tool_results."""
    tool = CountingTool()
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert len(state.tool_results) == 1
    assert state.tool_results[0].tool_name == "fake.read"


def test_runtime_saves_output_data_in_variables() -> None:
    """Runtime сохраняет output_data в state.variables['tool_outputs']."""
    tool = CountingTool()
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.variables["tool_outputs"]["fake.read"] == {"value": "ok"}


def test_runtime_does_not_bypass_tool_gateway() -> None:
    """Runtime не вызывает инструменты напрямую в обход Gateway."""
    tool = CountingTool()
    gateway = make_gateway(tool)
    runtime = SimpleAgentRuntime(gateway)
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    runtime.run(agent_spec, run_id="run-1")

    assert gateway.call_count == tool.execute_count == 1


def test_dangerous_tool_without_approval_pauses_for_human() -> None:
    """dangerous tool без approval переводит state в paused_for_human."""
    tool = CountingTool(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "dangerous",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.dangerous",
                next_on_success="final",
                next_on_error="final_failed",
            ),
            node("final", AgentGraphNodeType.FINAL),
            node("final_failed", AgentGraphNodeType.FINAL),
        ],
        [
            permission(
                "fake.dangerous",
                AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
            )
        ],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert tool.execute_count == 0


def test_write_tool_without_approval_pauses_without_execution() -> None:
    """write tool без approval не выполняется и ставит paused_for_human."""
    tool = CountingTool(
        name="fake.write",
        side_effect_level=ToolSideEffectLevel.WRITE,
        requires_human_approval=False,
    )
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "write",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.write",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.write", AgentActionLevel.WRITE)],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert tool.execute_count == 0


def test_paused_for_human_contains_pending_approval() -> None:
    """paused_for_human содержит pending_human_approval."""
    tool = CountingTool(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "dangerous",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.dangerous",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [
            permission(
                "fake.dangerous",
                AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
            )
        ],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.pending_human_approval is not None
    assert state.pending_human_approval.tool_name == "fake.dangerous"


def test_resume_approved_executes_dangerous_tool() -> None:
    """После resume approved=True dangerous tool выполняется."""
    tool = CountingTool(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "dangerous",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.dangerous",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [
            permission(
                "fake.dangerous",
                AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
            )
        ],
    )
    state = runtime.run(agent_spec, run_id="run-1")

    state = runtime.resume(agent_spec, state, approved=True)

    assert state.status == AgentRunStatus.COMPLETED
    assert tool.execute_count == 1


def test_resume_rejected_does_not_execute_dangerous_tool() -> None:
    """После resume approved=False dangerous tool не выполняется."""
    tool = CountingTool(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "dangerous",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.dangerous",
                next_on_success="final",
                next_on_error="final_failed",
            ),
            node("final", AgentGraphNodeType.FINAL),
            node("final_failed", AgentGraphNodeType.FINAL),
        ],
        [
            permission(
                "fake.dangerous",
                AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
            )
        ],
    )
    state = runtime.run(agent_spec, run_id="run-1")

    state = runtime.resume(agent_spec, state, approved=False)

    assert state.status == AgentRunStatus.FAILED
    assert tool.execute_count == 0


def test_max_steps_exceeded_marks_state_failed() -> None:
    """Превышение max_steps переводит state в failed."""
    runtime = SimpleAgentRuntime(make_gateway())
    agent_spec = make_agent_spec(
        [
            node("validate", AgentGraphNodeType.VALIDATION, next_on_success="plan"),
            node("plan", AgentGraphNodeType.PLANNING, next_on_success="final"),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [],
        limits=AgentRuntimeLimits(max_steps=1),
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.FAILED
    assert "Превышен лимит шагов выполнения" in state.errors


def test_tool_error_moves_to_next_on_error_when_present() -> None:
    """Ошибка инструмента переводит на next_on_error, если он есть."""
    tool = FailingTool()
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
                next_on_error="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.COMPLETED
    assert "fake failed" in state.errors


def test_tool_error_without_next_on_error_marks_failed() -> None:
    """Ошибка инструмента без next_on_error переводит state в failed."""
    tool = FailingTool()
    runtime = SimpleAgentRuntime(make_gateway(tool))
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.FAILED


def test_final_node_marks_completed() -> None:
    """final узел переводит state в completed."""
    runtime = SimpleAgentRuntime(make_gateway())
    agent_spec = make_agent_spec(
        [node("final", AgentGraphNodeType.FINAL)],
        [],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.COMPLETED


def test_final_failed_node_marks_failed() -> None:
    """final_failed узел переводит state в failed."""
    runtime = SimpleAgentRuntime(make_gateway())
    agent_spec = make_agent_spec(
        [node("final_failed", AgentGraphNodeType.FINAL)],
        [],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.FAILED


def test_run_repository_save_state_is_called_after_steps() -> None:
    """run_repository.save_state вызывается после шагов."""
    repository = FakeRunRepository()
    runtime = SimpleAgentRuntime(make_gateway(), run_repository=repository)
    agent_spec = make_agent_spec(
        [node("final", AgentGraphNodeType.FINAL)],
        [],
    )

    runtime.run(agent_spec, run_id="run-1")

    assert repository.create_run_count == 1
    assert repository.save_state_count >= 1


def test_save_state_error_does_not_crash_runtime() -> None:
    """Ошибка save_state не роняет Runtime, а добавляется в state.errors."""
    repository = FakeRunRepository(fail_on_save=True)
    runtime = SimpleAgentRuntime(make_gateway(), run_repository=repository)
    agent_spec = make_agent_spec(
        [node("final", AgentGraphNodeType.FINAL)],
        [],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.COMPLETED
    assert any("Ошибка сохранения состояния" in error for error in state.errors)
