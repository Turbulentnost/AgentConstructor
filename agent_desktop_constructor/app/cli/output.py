"""Форматированный вывод CLI на русском языке."""

from __future__ import annotations

from typing import Any

from agent_desktop_constructor.app.core.models.human_approval import HumanApprovalRecord
from agent_desktop_constructor.app.core.models.run_events import AgentRunEvent
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState
from agent_desktop_constructor.workers.models import WorkerResult


def print_section(title: str) -> None:
    """Напечатать заголовок секции."""
    print()
    print(f"=== {title} ===")


def print_agent_spec(agent_spec: AgentSpec) -> None:
    """Напечатать ключевые поля AgentSpec."""
    print_section("Агент")
    print(f"agent_id: {agent_spec.agent_id}")
    print(f"Название: {agent_spec.name}")
    print(f"Описание: {agent_spec.description}")
    print(f"Цель: {agent_spec.goal.main_goal}")

    print_section("Требования к данным")
    if not agent_spec.data_requirements:
        print("- нет")
    for requirement in agent_spec.data_requirements:
        print(
            "- "
            f"{requirement.name}: {requirement.description}; "
            f"source={requirement.source_type}; "
            f"required={requirement.required}; "
            f"can_agent_find={requirement.can_agent_find}; "
            f"default={requirement.default_value}; "
            f"ask_human_if_missing={requirement.ask_human_if_missing}"
        )

    print_section("Инструменты")
    for tool in agent_spec.tools:
        print(
            "- "
            f"{tool.tool_name} [{tool.action_level.value}] "
            f"approval={tool.requires_human_approval} "
            f"allowed={tool.allowed}"
        )

    print_section("Граф")
    for index, node in enumerate(agent_spec.graph_nodes, start=1):
        target = node.next_on_success or "конец"
        tool_suffix = f" tool={node.tool_name}" if node.tool_name else ""
        print(f"{index}. {node.node_id} -> {target}{tool_suffix}")

    print_section("Runtime limits")
    limits = agent_spec.runtime_limits
    print(f"max_steps: {limits.max_steps}")
    print(f"max_tool_calls: {limits.max_tool_calls}")
    print(f"max_retries_per_tool: {limits.max_retries_per_tool}")
    print(f"low_confidence_threshold: {limits.low_confidence_threshold}")


def print_runtime_state(state: AgentRuntimeState) -> None:
    """Напечатать краткий итог запуска runtime."""
    print_section("Результат запуска")
    print(f"run_id: {state.run_id}")
    print(f"Статус: {state.status.value}")
    print(f"Текущий узел: {state.current_node_id}")
    print(f"Шагов: {state.step_counter}")
    print(f"Вызовов инструментов: {state.tool_call_counter}")

    if state.pending_human_approval is not None:
        approval = state.pending_human_approval
        print("Ожидает подтверждения человека:")
        print(f"- node_id: {approval.node_id}")
        print(f"- tool_name: {approval.tool_name}")
        print(f"- вопрос: {approval.question}")

    if state.errors:
        print_section("Ошибки")
        for error in state.errors:
            print(f"- {_friendly_error(error)}")

    report_text = _extract_report_text(state)
    if report_text:
        print_section("Итоговый отчёт")
        print(report_text)


def print_tool_results(state: AgentRuntimeState) -> None:
    """Напечатать результаты вызовов инструментов runtime."""
    print_section("Вызванные инструменты")
    if not state.tool_results:
        print("- нет")
        return

    for index, result in enumerate(state.tool_results, start=1):
        status = "ok" if result.ok else "error"
        print(f"{index}. {result.tool_name}: {status}")
        if result.error_type:
            print(f"   error_type: {result.error_type}")
        if result.error_message:
            print(f"   error_message: {_friendly_error(result.error_message)}")
        if result.output_data:
            print(f"   output: {_summarize_output(result.output_data)}")


def print_worker_result(result: WorkerResult) -> None:
    """Напечатать WorkerResult, включая diagnostics steps."""
    print_section("Результат worker")
    print(f"task_id: {result.task_id}")
    print(f"ok: {result.ok}")
    print(f"error_type: {result.error_type}")
    print(f"error_message: {_friendly_error(result.error_message)}")

    output_data = result.output_data or {}
    diagnostics = output_data.get("diagnostics", {})
    steps = diagnostics.get("steps", [])
    if steps:
        print_section("Шаги диагностики")
        for step in steps:
            print(
                "- "
                f"{step.get('step')}: ok={step.get('ok')} "
                f"message={step.get('message')}"
            )
            if step.get("error_type") or step.get("error_message"):
                print(
                    "  "
                    f"error_type={step.get('error_type')} "
                    f"error_message={step.get('error_message')}"
                )

    recommendations = diagnostics.get("recommendations", [])
    if recommendations:
        print_section("Рекомендации")
        for recommendation in recommendations:
            print(f"- {recommendation}")


def print_agent_list(agents: list[AgentSpec]) -> None:
    """Напечатать список сохранённых агентов."""
    print_section("Сохранённые агенты")
    if not agents:
        print("Сохранённых агентов пока нет.")
        return

    for index, agent in enumerate(agents, start=1):
        print(f"{index}. agent_id: {agent.agent_id}")
        print(f"   name: {agent.name}")
        print(f"   description: {_truncate_text(agent.description)}")
        print(f"   graph_nodes: {len(agent.graph_nodes)}")
        print(f"   tools: {len(agent.tools)}")
        print(f"   goal: {_truncate_text(agent.goal.main_goal)}")


def print_run_list(states: list[AgentRuntimeState]) -> None:
    """Напечатать список запусков агента."""
    print_section("Запуски агента")
    if not states:
        print("У этого агента пока нет запусков.")
        return

    for index, state in enumerate(states, start=1):
        has_approval = "да" if state.pending_human_approval is not None else "нет"
        print(f"{index}. run_id: {state.run_id}")
        print(f"   status: {state.status.value}")
        print(f"   current_node_id: {state.current_node_id}")
        print(f"   steps: {state.step_counter}")
        print(f"   tool_calls: {state.tool_call_counter}")
        print(f"   human approval: {has_approval}")
        print(f"   errors: {len(state.errors)}")


def print_run_details(state: AgentRuntimeState) -> None:
    """Напечатать подробное состояние запуска."""
    print_section("Состояние запуска")
    print(f"run_id: {state.run_id}")
    print(f"agent_id: {state.agent_id}")
    print(f"Статус: {state.status.value}")
    print(f"Текущий узел: {state.current_node_id}")
    print(f"Шагов: {state.step_counter}")
    print(f"Вызовов инструментов: {state.tool_call_counter}")

    print_section("Variables")
    if state.variables:
        for key, value in state.variables.items():
            print(f"- {key}: {_format_value(value)}")
    else:
        print("- нет")

    print_section("Ошибки")
    if state.errors:
        for error in state.errors:
            print(f"- {_friendly_error(error)}")
    else:
        print("Ошибок нет.")

    print_tool_results(state)
    print_human_approval(state)


def print_run_events(events: list[AgentRunEvent], verbose: bool = False) -> None:
    """Напечатать события запуска в хронологическом порядке."""
    print_section("События запуска")
    if not events:
        print("Для этого запуска событий пока нет.")
        return

    for event in events:
        timestamp = event.created_at.strftime("%Y-%m-%d %H:%M:%S")
        parts = [timestamp, event.event_type.value]
        if event.node_id:
            parts.append(event.node_id)
        if event.tool_name:
            parts.append(event.tool_name)
        parts.append(event.message)
        print(" | ".join(parts))
        if verbose and event.details:
            print(f"   details: {_format_value(event.details)}")


def print_human_approval(state: AgentRuntimeState) -> None:
    """Напечатать pending_human_approval, если он есть."""
    approval = state.pending_human_approval
    if approval is None:
        return

    print_section("Требуется подтверждение человека")
    print(f"approval_id: {approval.approval_id}")
    print(f"node_id: {approval.node_id}")
    print(f"tool_name: {approval.tool_name}")
    print(f"question: {approval.question}")
    print("options:")
    for option in approval.options:
        print(f"- {option}")


def print_approval_list(records: list[HumanApprovalRecord]) -> None:
    """Напечатать очередь ожидающих подтверждений."""
    print_section("Ожидающие подтверждения")
    if not records:
        print("Ожидающих подтверждений нет.")
        return

    for index, record in enumerate(records, start=1):
        print(f"{index}. approval_id: {record.approval_id}")
        print(f"   run_id: {record.run_id}")
        print(f"   agent_id: {record.agent_id}")
        print(f"   node_id: {record.node_id}")
        print(f"   tool_name: {record.tool_name}")
        print(f"   question: {_truncate_text(record.question)}")
        print(f"   created_at: {record.created_at.isoformat()}")


def print_approval_details(record: HumanApprovalRecord) -> None:
    """Напечатать подробности запроса подтверждения."""
    print_section("Подтверждение человека")
    print(f"approval_id: {record.approval_id}")
    print(f"run_id: {record.run_id}")
    print(f"agent_id: {record.agent_id}")
    print(f"status: {record.status.value}")
    print(f"node_id: {record.node_id}")
    print(f"tool_name: {record.tool_name}")
    print(f"question: {record.question}")
    print("options:")
    for option in record.options:
        print(f"- {option}")
    print(f"selected_option: {record.selected_option}")
    print(f"comment: {record.comment}")
    print(f"created_at: {record.created_at.isoformat()}")
    print(f"answered_at: {record.answered_at.isoformat() if record.answered_at else None}")


def print_approval_result(state: AgentRuntimeState) -> None:
    """Напечатать итог approve/reject команды."""
    print_section("Результат подтверждения")
    print(f"run_id: {state.run_id}")
    print(f"agent_id: {state.agent_id}")
    print(f"Статус запуска: {state.status.value}")
    print(f"Текущий узел: {state.current_node_id}")
    if state.errors:
        print_section("Ошибки")
        for error in state.errors:
            print(f"- {_friendly_error(error)}")


def print_storage_error(error: Exception) -> None:
    """Напечатать понятную ошибку SQLite/storage."""
    print_section("Ошибка хранилища")
    print(f"{type(error).__name__}: {_truncate_text(str(error), 300)}")


def _extract_report_text(state: AgentRuntimeState) -> str | None:
    """Достать report_text из стандартного output report tool."""
    tool_outputs = state.variables.get("tool_outputs", {})
    report_output = tool_outputs.get("report.build_task_report", {})
    report_text = report_output.get("report_text")
    if isinstance(report_text, str) and report_text.strip():
        return report_text
    return None


def _summarize_output(output_data: dict[str, Any]) -> str:
    """Сжато описать output_data, не печатая большие payload полностью."""
    parts: list[str] = []
    for key, value in output_data.items():
        if isinstance(value, list):
            parts.append(f"{key}: {len(value)} item(s)")
        elif isinstance(value, dict):
            parts.append(f"{key}: object({len(value)})")
        else:
            text = str(value)
            if len(text) > 120:
                text = text[:117] + "..."
            parts.append(f"{key}: {text}")
    return "; ".join(parts)


def _format_value(value: Any) -> str:
    """Безопасно и кратко отформатировать значение для CLI."""
    if isinstance(value, dict):
        parts = []
        for key, nested_value in list(value.items())[:10]:
            parts.append(f"{key}={_format_value(nested_value)}")
        suffix = "; ..." if len(value) > 10 else ""
        return "{" + "; ".join(parts) + suffix + "}"
    if isinstance(value, list):
        preview = ", ".join(_format_value(item) for item in value[:5])
        suffix = ", ..." if len(value) > 5 else ""
        return "[" + preview + suffix + "]"
    return _truncate_text(str(value))


def _truncate_text(value: str, limit: int = 160) -> str:
    """Ограничить потенциально большой или чувствительный вывод."""
    redacted = value.replace("token=", "token=<hidden>")
    redacted = redacted.replace("password=", "password=<hidden>")
    if len(redacted) <= limit:
        return redacted
    return redacted[: limit - 3] + "..."


def _friendly_error(message: str | None) -> str | None:
    """Вернуть понятный текст ошибки без traceback."""
    if message is None:
        return None
    if "WORKER_TIMEOUT" in message or "COM worker не ответил" in message:
        return (
            f"{message} | Outlook COM мог зависнуть на одном из MAPI-шагов. "
            "Проверьте, открыт ли Outlook и нет ли модальных окон."
        )
    return message

