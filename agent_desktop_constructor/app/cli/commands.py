"""Команды CLI для проверки ядра AgentConstructor без UI."""

from __future__ import annotations

from agent_desktop_constructor.app.cli.output import (
    print_agent_list,
    print_agent_spec,
    print_approval_details,
    print_approval_list,
    print_approval_result,
    print_human_approval,
    print_run_details,
    print_run_events,
    print_run_list,
    print_runtime_state,
    print_section,
    print_storage_error,
    print_tool_results,
    print_worker_result,
)
from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import (
    AppConfig,
    load_app_config_from_env,
)
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.workers.models import WorkerTask
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker

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
    container = build_application_container(_config_for_mode(AppRunMode.OFFLINE))
    agent_spec = container.agent_service.build_preview(user_request)
    print_agent_spec(agent_spec)
    return 0


def run_fake(user_request: str) -> int:
    """Запустить агента на fake tools без Outlook и COM."""
    container = build_application_container(_config_for_mode(AppRunMode.FAKE))
    agent_spec = container.agent_service.create_agent_from_request(
        user_request,
        save=False,
    )
    state = container.agent_service.run_agent_spec(agent_spec)
    print_runtime_state(state)
    print_tool_results(state)
    return 0


def run_outlook_readonly(user_request: str) -> int:
    """Запустить агента на real Outlook COM-backed read-only tools."""
    container = build_application_container(
        _config_for_mode(AppRunMode.OUTLOOK_READONLY)
    )
    agent_spec = container.agent_service.create_agent_from_request(
        user_request,
        save=False,
    )
    state = container.agent_service.run_agent_spec(agent_spec)
    print_runtime_state(state)
    print_tool_results(state)
    _print_known_runtime_errors(state.errors)
    return 0


def diagnose_outlook() -> int:
    """Запустить read-only диагностику Outlook COM/MAPI через subprocess worker."""
    worker = SubprocessComWorker()
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


def test_send_block() -> int:
    """Проверить блокировку email.send на уровне gateway и worker safe mode."""
    container = build_application_container(
        _config_for_mode(AppRunMode.OUTLOOK_READONLY)
    )
    agent_spec = container.agent_service.create_agent_from_request(
        "Отправь отчёт руководителю по почте после проверки Outlook и поручений",
        save=False,
    )
    without_approval = container.tool_gateway.execute_tool(
        agent_spec=agent_spec,
        run_id="cli-send-block",
        tool_name="email.send",
        input_data={"to": "blocked@example.com"},
        human_approved=False,
    )
    with_approval = container.tool_gateway.execute_tool(
        agent_spec=agent_spec,
        run_id="cli-send-block",
        tool_name="email.send",
        input_data={"to": "blocked@example.com"},
        human_approved=True,
    )
    _print_send_block_results(without_approval, with_approval)
    return 0


def create_agent(user_request: str) -> int:
    """Создать и сохранить агента в SQLite."""
    try:
        container = build_application_container()
        agent_spec = container.agent_service.create_agent_from_request(
            user_request,
            save=True,
        )
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_section("Агент сохранён")
    print(f"agent_id: {agent_spec.agent_id}")
    print(f"name: {agent_spec.name}")
    return 0


def list_agents() -> int:
    """Показать сохранённых агентов из SQLite."""
    try:
        container = build_application_container()
        agents = container.agent_service.list_agents()
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_agent_list(agents)
    return 0


def run_agent(agent_id: str) -> int:
    """Запустить сохранённого агента."""
    try:
        container = build_application_container()
        state = container.agent_service.run_agent(agent_id)
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_runtime_state(state)
    print_tool_results(state)
    print_human_approval(state)
    _print_known_runtime_errors(state.errors)
    return 0


def list_runs(agent_id: str) -> int:
    """Показать запуски сохранённого агента."""
    try:
        container = build_application_container()
        states = container.run_repository.list_runs(agent_id)
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_run_list(states)
    return 0


def show_run(run_id: str) -> int:
    """Показать сохранённое состояние запуска."""
    try:
        container = build_application_container()
        state = container.run_repository.get_state(run_id)
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_run_details(state)
    return 0


def show_events(run_id: str, verbose: bool = False) -> int:
    """Показать журнал событий запуска."""
    try:
        container = build_application_container()
        events = container.run_event_repository.list_events(run_id)
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_run_events(events, verbose=verbose)
    return 0


def list_approvals() -> int:
    """Показать очередь ожидающих подтверждений."""
    try:
        container = build_application_container()
        records = container.agent_service.list_pending_approvals()
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_approval_list(records)
    return 0


def show_approval(approval_id: str) -> int:
    """Показать подробности запроса подтверждения."""
    try:
        container = build_application_container()
        record = container.agent_service.get_approval(approval_id)
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_approval_details(record)
    return 0


def approve(approval_id: str) -> int:
    """Подтвердить запрос и продолжить запуск."""
    try:
        container = build_application_container()
        state = container.agent_service.resume_run_by_approval(
            approval_id,
            approved=True,
        )
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_approval_result(state)
    print_tool_results(state)
    print_human_approval(state)
    _print_known_runtime_errors(state.errors)
    return 0


def reject(approval_id: str, comment: str) -> int:
    """Отклонить запрос и продолжить запуск."""
    try:
        container = build_application_container()
        state = container.agent_service.resume_run_by_approval(
            approval_id,
            approved=False,
            comment=comment,
        )
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_approval_result(state)
    print_tool_results(state)
    print_human_approval(state)
    _print_known_runtime_errors(state.errors)
    return 0


def resume_run(
    agent_id: str,
    run_id: str,
    *,
    approved: bool,
    comment: str | None = None,
) -> int:
    """Продолжить запуск после HumanApproval."""
    try:
        container = build_application_container()
        agent_spec = container.agent_service.get_agent(agent_id)
        state = container.run_repository.get_state(run_id)
        if state.agent_id != agent_id:
            print("agent_id не соответствует запуску.")
            return 1
        if state.status != AgentRunStatus.PAUSED_FOR_HUMAN:
            print("Этот запуск не ожидает подтверждения человека.")
            return 1
        state = container.agent_service.resume_run(
            agent_spec,
            state,
            approved=approved,
            comment=comment,
        )
    except Exception as exc:
        print_storage_error(exc)
        return 1

    print_runtime_state(state)
    print_tool_results(state)
    print_human_approval(state)
    _print_known_runtime_errors(state.errors)
    return 0


def _print_send_block_results(without_approval, with_approval) -> None:
    """Напечатать единый отчёт test-send-block."""
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


def _config_for_mode(run_mode: AppRunMode) -> AppConfig:
    """Загрузить env-конфигурацию и переопределить только run_mode."""
    return load_app_config_from_env().model_copy(update={"run_mode": run_mode})


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

