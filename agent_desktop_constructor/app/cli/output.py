"""Форматированный вывод CLI на русском языке."""

from __future__ import annotations

from typing import Any

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

