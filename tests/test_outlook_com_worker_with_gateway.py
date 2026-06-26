"""Интеграция OutlookComWorker с ComBackedTool и ToolGateway."""

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
from agent_desktop_constructor.tools.com_backed_tools import register_outlook_com_tools
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers import outlook_com_worker
from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask
from agent_desktop_constructor.workers.outlook_com_errors import ComUnavailableError
from agent_desktop_constructor.workers.outlook_com_worker import OutlookComWorker


class CountingOutlookComWorker(OutlookComWorker):
    """OutlookComWorker со счётчиком вызовов execute."""

    def __init__(self, safe_mode: bool = True) -> None:
        """Создать worker со счётчиком."""
        super().__init__(safe_mode=safe_mode)
        self.execute_count = 0

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Увеличить счётчик и выполнить обычную safe-mode логику."""
        self.execute_count += 1
        return super().execute(task)


def make_outlook_agent_spec() -> AgentSpec:
    """Создать AgentSpec для проверки Outlook COM tools через gateway."""
    return AgentSpec(
        agent_id="outlook-agent",
        name="Outlook Agent",
        description="Агент для проверки OutlookComWorker",
        goal=AgentGoal(
            main_goal="Проверить безопасный Outlook COM worker",
            success_criteria=["Worker вернул структурированный результат"],
            forbidden_actions=["Не отправлять письма без подтверждения"],
        ),
        data_requirements=[],
        tools=[
            AgentToolPermission(
                tool_name="outlook.search_mail",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            ),
            AgentToolPermission(
                tool_name="outlook.read_calendar",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            ),
            AgentToolPermission(
                tool_name="email.send",
                action_level=AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
                allowed=True,
            ),
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


def make_gateway(worker: OutlookComWorker) -> ToolGateway:
    """Зарегистрировать Outlook COM tools и вернуть ToolGateway."""
    registry = ToolRegistry()
    register_outlook_com_tools(registry, worker)
    return ToolGateway(registry)


def test_outlook_search_mail_through_gateway_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """outlook.search_mail через gateway не падает при недоступном COM."""

    def raise_com_unavailable(input_data: dict) -> dict:
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(outlook_com_worker, "search_mail", raise_com_unavailable)
    gateway = make_gateway(
        OutlookComWorker(safe_mode=True, allow_direct_com_calls=True)
    )

    result = gateway.execute_tool(
        agent_spec=make_outlook_agent_spec(),
        run_id="run-1",
        tool_name="outlook.search_mail",
        input_data={"days": 7},
    )

    assert result.ok is False
    assert result.error_type == "COM_NOT_AVAILABLE"


def test_outlook_read_calendar_through_gateway_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """outlook.read_calendar через gateway не падает при недоступном COM."""

    def raise_com_unavailable(input_data: dict) -> dict:
        raise ComUnavailableError("COM недоступен в тесте")

    monkeypatch.setattr(outlook_com_worker, "read_calendar", raise_com_unavailable)
    gateway = make_gateway(
        OutlookComWorker(safe_mode=True, allow_direct_com_calls=True)
    )

    result = gateway.execute_tool(
        agent_spec=make_outlook_agent_spec(),
        run_id="run-1",
        tool_name="outlook.read_calendar",
        input_data={"days_forward": 7},
    )

    assert result.ok is False
    assert result.error_type == "COM_NOT_AVAILABLE"


def test_email_send_without_human_approval_does_not_call_worker() -> None:
    """ToolGateway останавливает email.send до worker-а без HumanApproval."""
    worker = CountingOutlookComWorker(safe_mode=True)
    gateway = make_gateway(worker)

    result = gateway.execute_tool(
        agent_spec=make_outlook_agent_spec(),
        run_id="run-1",
        tool_name="email.send",
        input_data={"to": "boss@example.com"},
        human_approved=False,
    )

    assert result.ok is False
    assert result.requires_human_approval is True
    assert result.error_type == "HUMAN_APPROVAL_REQUIRED"
    assert worker.execute_count == 0


def test_email_send_with_human_approval_still_blocked_by_worker() -> None:
    """HumanApproval разрешает попытку, но safe-mode worker не отправляет письмо."""
    worker = CountingOutlookComWorker(safe_mode=True)
    gateway = make_gateway(worker)

    result = gateway.execute_tool(
        agent_spec=make_outlook_agent_spec(),
        run_id="run-1",
        tool_name="email.send",
        input_data={"to": "boss@example.com"},
        human_approved=True,
    )

    assert result.ok is False
    assert result.error_type == "SEND_DISABLED_FOR_SAFETY"
    assert worker.execute_count == 1
