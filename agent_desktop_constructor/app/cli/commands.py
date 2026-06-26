"""Команды CLI для проверки ядра AgentConstructor без UI."""

from __future__ import annotations

from typing import Callable

from agent_desktop_constructor.app.cli.output import (
    print_agent_spec,
    print_runtime_state,
    print_section,
    print_tool_results,
    print_worker_result,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.com_backed_tools import (
    EmailSendComTool,
    register_outlook_com_tools,
)
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeReportBuildTaskReportTool,
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.workers.base import BaseWorker
from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker

WorkerFactory = Callable[[], BaseWorker]

NORMAL_ERROR_TYPES = {
    "COM_NOT_AVAILABLE",
    "WORKER_TIMEOUT",
    "OUTLOOK_ACCESS_ERROR",
    "UNKNOWN_COM_TOOL",
    "OUTLOOK_COM_ERROR",
    "OUTLOOK_TOOL_NOT_IMPLEMENTED",
    "HUMAN_APPROVAL_REQUIRED",
    "SEND_DISABLED_FOR_SAFETY",
    "DANGEROUS_ACTION_BLOCKED",
    "DRAFT_DISABLED_FOR_SAFETY",
    "INVALID_WORKER_RESPONSE",
}


def build_agent(user_request: str) -> int:
    """Собрать AgentSpec и вывести его без запуска инструментов."""
    agent_spec = _build_agent_spec(user_request)
    print_agent_spec(agent_spec)
    return 0


def run_fake(user_request: str) -> int:
    """Запустить агента на fake tools без Outlook и COM."""
    agent_spec = _build_agent_spec(user_request)
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    state = _run_agent(agent_spec, registry)
    print_runtime_state(state)
    print_tool_results(state)
    return 0


def run_outlook_readonly(
    user_request: str,
    worker_factory: WorkerFactory | None = None,
) -> int:
    """Запустить агента на real Outlook COM-backed read-only tools."""
    agent_spec = _build_agent_spec(user_request)
    worker = _make_worker(worker_factory)
    registry = ToolRegistry()
    register_outlook_com_tools(registry, worker)
    registry.register(FakeReportBuildTaskReportTool())

    state = _run_agent(agent_spec, registry)
    print_runtime_state(state)
    print_tool_results(state)
    _print_known_runtime_errors(state.errors)
    return 0


def diagnose_outlook(worker_factory: WorkerFactory | None = None) -> int:
    """Запустить read-only диагностику Outlook COM/MAPI через subprocess worker."""
    worker = _make_worker(worker_factory)
    task = WorkerTask(
        task_id="cli-outlook-diagnostics",
        tool_name="outlook.diagnostics",
        input_data={},
        timeout_seconds=15,
    )
    result = worker.execute(task)
    print_worker_result(result)
    if result.error_type == "WORKER_TIMEOUT":
        print()
        print("Outlook COM завис на одном из шагов диагностики.")
    return 0


def test_send_block(worker_factory: WorkerFactory | None = None) -> int:
    """Проверить блокировку email.send на уровне gateway и worker safe mode."""
    agent_spec = _build_agent_spec(
        "Отправь отчёт руководителю по почте после проверки Outlook и поручений"
    )
    worker = _make_worker(worker_factory)
    registry = ToolRegistry()
    registry.register(EmailSendComTool(worker))
    gateway = ToolGateway(registry)

    without_approval = gateway.execute_tool(
        agent_spec=agent_spec,
        run_id="cli-send-block",
        tool_name="email.send",
        input_data={"to": "blocked@example.com"},
        human_approved=False,
    )
    with_approval = gateway.execute_tool(
        agent_spec=agent_spec,
        run_id="cli-send-block",
        tool_name="email.send",
        input_data={"to": "blocked@example.com"},
        human_approved=True,
    )

    real_send_executed = bool(
        with_approval.ok
        and (with_approval.output_data or {}).get("sent") is True
        and with_approval.error_type is None
    )

    print_section("Проверка блокировки отправки")
    print(
        "gateway_without_approval: "
        f"{without_approval.error_type} "
        "(ожидается HUMAN_APPROVAL_REQUIRED)"
    )
    print(
        "gateway_with_approval: "
        f"{with_approval.error_type} "
        "(ожидается SEND_DISABLED_FOR_SAFETY)"
    )
    print(f"real_send_executed: {str(real_send_executed).lower()}")

    if with_approval.error_message:
        print(f"worker_message: {with_approval.error_message}")

    return 0


def _build_agent_spec(user_request: str) -> AgentSpec:
    """Создать AgentSpec из пользовательского запроса."""
    return AgentBuilder().build_from_request(user_request)


def _run_agent(agent_spec: AgentSpec, registry: ToolRegistry):
    """Запустить AgentSpec через стандартные ToolGateway и SimpleAgentRuntime."""
    gateway = ToolGateway(registry)
    runtime = SimpleAgentRuntime(gateway)
    return runtime.run(agent_spec)


def _make_worker(worker_factory: WorkerFactory | None) -> BaseWorker:
    """Создать worker; в unit-тестах можно подменить фабрику."""
    if worker_factory is not None:
        return worker_factory()
    return SubprocessComWorker()


def _print_known_runtime_errors(errors: list[str]) -> None:
    """Отдельно подсветить обычные COM/Gateway ошибки."""
    known_errors = [
        error
        for error in errors
        if any(error_type in error for error_type in NORMAL_ERROR_TYPES)
    ]
    if not known_errors:
        return

    print_section("Обычные ошибки внешних интеграций")
    for error in known_errors:
        print(f"- {error}")

