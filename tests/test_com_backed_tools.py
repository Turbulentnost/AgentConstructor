"""Тесты COM-backed tools без реального COM."""

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
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.com_backed_tools import (
    EmailSendComTool,
    OutlookSearchMailComTool,
    register_outlook_com_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.fake_com_worker import FakeComWorker
from agent_desktop_constructor.workers.models import WorkerTask


class RaisingWorker(FakeComWorker):
    """Fake worker, выбрасывающий исключение для проверки обработки ошибок."""

    def execute(self, task: WorkerTask):
        """Выбросить ошибку worker-а."""
        raise RuntimeError("worker boom")


def make_email_send_agent_spec() -> AgentSpec:
    """Создать AgentSpec с разрешением на email.send."""
    return AgentSpec(
        agent_id="agent-1",
        name="Тестовый агент",
        description="Тестовый агент для email.send",
        goal=AgentGoal(
            main_goal="Проверить COM-backed email.send",
            success_criteria=["Проверка завершена"],
            forbidden_actions=["Не отправлять без подтверждения"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name="email.send",
                action_level=AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
                allowed=True,
            )
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Завершить",
                description="Финальный узел",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            )
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def test_outlook_search_mail_com_tool_returns_success_result() -> None:
    """OutlookSearchMailComTool создаёт WorkerTask и возвращает ToolCallResult ok=True."""
    worker = FakeComWorker(
        responses={
            "outlook.search_mail": {"messages": [{"id": "mail-1"}]},
        }
    )
    tool = OutlookSearchMailComTool(worker)

    result = tool.execute({"days": 7})

    assert isinstance(result, ToolCallResult)
    assert result.ok is True
    assert result.tool_name == "outlook.search_mail"
    assert result.output_data == {"messages": [{"id": "mail-1"}]}


def test_com_backed_tool_converts_worker_error_to_tool_error() -> None:
    """Если worker возвращает ошибку, инструмент возвращает ToolCallResult ok=False."""
    worker = FakeComWorker()
    tool = OutlookSearchMailComTool(worker)

    result = tool.execute({})

    assert result.ok is False
    assert result.error_type == "FAKE_RESPONSE_NOT_FOUND"


def test_com_backed_tool_converts_worker_exception_to_tool_error() -> None:
    """Если worker выбрасывает exception, инструмент возвращает WORKER_EXECUTION_ERROR."""
    tool = OutlookSearchMailComTool(RaisingWorker())

    result = tool.execute({})

    assert result.ok is False
    assert result.error_type == "WORKER_EXECUTION_ERROR"
    assert result.error_message == "worker boom"


def test_email_send_com_tool_is_dangerous() -> None:
    """EmailSendComTool имеет side_effect_level dangerous."""
    tool = EmailSendComTool(FakeComWorker(responses={"email.send": {"sent": True}}))

    assert tool.definition.side_effect_level == ToolSideEffectLevel.DANGEROUS


def test_email_send_com_tool_requires_human_approval() -> None:
    """EmailSendComTool requires_human_approval=True."""
    tool = EmailSendComTool(FakeComWorker(responses={"email.send": {"sent": True}}))

    assert tool.definition.requires_human_approval is True


def test_register_outlook_com_tools_registers_all_tools() -> None:
    """register_outlook_com_tools регистрирует все Outlook COM-backed tools."""
    registry = ToolRegistry()
    register_outlook_com_tools(registry, FakeComWorker())

    assert registry.list_tool_names() == {
        "outlook.search_mail",
        "outlook.read_calendar",
        "outlook.read_tasks",
        "email.create_draft",
        "email.send",
    }


def test_tool_gateway_blocks_email_send_without_human_approval() -> None:
    """Через ToolGateway email.send без human_approved блокируется."""
    registry = ToolRegistry()
    registry.register(EmailSendComTool(FakeComWorker(responses={"email.send": {"sent": True}})))
    gateway = ToolGateway(registry)

    result = gateway.execute_tool(
        agent_spec=make_email_send_agent_spec(),
        run_id="run-1",
        tool_name="email.send",
        input_data={},
        human_approved=False,
    )

    assert result.ok is False
    assert result.requires_human_approval is True
    assert result.error_type == "HUMAN_APPROVAL_REQUIRED"


def test_tool_gateway_executes_email_send_with_human_approval() -> None:
    """Через ToolGateway email.send с human_approved=True выполняется."""
    registry = ToolRegistry()
    registry.register(
        EmailSendComTool(
            FakeComWorker(responses={"email.send": {"sent": True, "message_id": "sent-1"}})
        )
    )
    gateway = ToolGateway(registry)

    result = gateway.execute_tool(
        agent_spec=make_email_send_agent_spec(),
        run_id="run-1",
        tool_name="email.send",
        input_data={},
        human_approved=True,
    )

    assert result.ok is True
    assert result.output_data == {"sent": True, "message_id": "sent-1"}
