"""Тесты runtime input_data для tool calls."""

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
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


class FirstTool(BaseTool):
    """Первый tool, создающий output."""

    def __init__(self) -> None:
        super().__init__(_definition("test.first"))

    def execute(self, input_data: dict) -> ToolCallResult:
        return ToolCallResult(ok=True, tool_name=self.definition.name, output_data={"x": 1})


class CaptureInputTool(BaseTool):
    """Tool, сохраняющий input_data."""

    def __init__(self) -> None:
        super().__init__(_definition("test.capture"))
        self.last_input: dict | None = None

    def execute(self, input_data: dict) -> ToolCallResult:
        self.last_input = input_data
        return ToolCallResult(ok=True, tool_name=self.definition.name, output_data={})


def test_runtime_passes_tool_outputs_to_next_tool() -> None:
    """Runtime передаёт tool_outputs в LLM analysis и другие tools."""
    registry = ToolRegistry()
    first = FirstTool()
    capture = CaptureInputTool()
    registry.register(first)
    registry.register(capture)
    runtime = SimpleAgentRuntime(ToolGateway(registry))
    agent_spec = _agent_spec()

    runtime.run(agent_spec, {"user_request": "run"})

    assert capture.last_input is not None
    assert capture.last_input["tool_outputs"]["test.first"] == {"x": 1}
    assert capture.last_input["runtime_context"]["agent_id"] == "agent-1"
    assert capture.last_input["user_request"] == "run"


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        title=name,
        description=name,
        side_effect_level=ToolSideEffectLevel.READ,
        execution_mode=ToolExecutionMode.LOCAL,
        requires_human_approval=False,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def _agent_spec() -> AgentSpec:
    return AgentSpec(
        agent_id="agent-1",
        name="Agent",
        description="Agent",
        goal=AgentGoal(
            main_goal="Goal",
            success_criteria=["ok"],
            forbidden_actions=["none"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name="test.first",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            ),
            AgentToolPermission(
                tool_name="test.capture",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            ),
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="first",
                node_type=AgentGraphNodeType.TOOL_CALL,
                title="First",
                description="First",
                tool_name="test.first",
                next_on_success="capture",
                next_on_error="final_failed",
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="capture",
                node_type=AgentGraphNodeType.TOOL_CALL,
                title="Capture",
                description="Capture",
                tool_name="test.capture",
                next_on_success="final",
                next_on_error="final_failed",
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Final",
                description="Final",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final_failed",
                node_type=AgentGraphNodeType.FINAL,
                title="Failed",
                description="Failed",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
        ],
        runtime_limits=AgentRuntimeLimits(),
    )

