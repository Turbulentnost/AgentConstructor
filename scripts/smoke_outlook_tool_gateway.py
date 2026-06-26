"""Ручная smoke-проверка Outlook COM через ToolGateway."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from agent_desktop_constructor.workers import com_availability
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def main() -> int:
    """Запустить ручную проверку ToolGateway -> ComBackedTool -> OutlookComWorker."""
    try:
        print("Outlook COM ToolGateway smoke-check")
        print(f"OS: {platform.platform()}")
        print(f"Windows: {com_availability.is_windows()}")
        print(f"pywin32 available: {com_availability.is_pywin32_available()}")
        print(f"COM status: {com_availability.get_com_unavailable_reason()}")
        print()

        worker = SubprocessComWorker()
        registry = ToolRegistry()
        register_outlook_com_tools(registry, worker)
        gateway = ToolGateway(registry)
        agent_spec = _make_agent_spec()

        mail_result = gateway.execute_tool(
            agent_spec=agent_spec,
            run_id="smoke-run",
            tool_name="outlook.search_mail",
            input_data={
                "folder": "Inbox",
                "days": 7,
                "query": None,
                "max_results": 5,
                "max_scan_items": 100,
            },
        )
        _print_result("Inbox messages via ToolGateway", mail_result, "messages")

        calendar_result = gateway.execute_tool(
            agent_spec=agent_spec,
            run_id="smoke-run",
            tool_name="outlook.read_calendar",
            input_data={
                "days_forward": 7,
                "max_results": 5,
                "max_scan_items": 100,
            },
        )
        _print_result("Calendar events via ToolGateway", calendar_result, "events")

        blocked_without_approval = gateway.execute_tool(
            agent_spec=agent_spec,
            run_id="smoke-run",
            tool_name="email.send",
            input_data={"to": "nobody@example.com"},
            human_approved=False,
        )
        _print_basic_result("email.send without HumanApproval", blocked_without_approval)

        blocked_with_approval = gateway.execute_tool(
            agent_spec=agent_spec,
            run_id="smoke-run",
            tool_name="email.send",
            input_data={"to": "nobody@example.com"},
            human_approved=True,
        )
        _print_basic_result("email.send with HumanApproval", blocked_with_approval)

        read_ok = mail_result.ok or calendar_result.ok
        send_blocked = (
            blocked_without_approval.requires_human_approval
            and blocked_with_approval.error_type == "SEND_DISABLED_FOR_SAFETY"
        )
        read_text = "работает" if read_ok else "не работает или COM недоступен"
        send_text = "заблокирована" if send_blocked else "требует проверки"
        print()
        print(f"Проверка завершена. Чтение {read_text}. Отправка {send_text}.")
        return 0
    except Exception as exc:
        print(f"Необработанная ошибка smoke-скрипта: {exc}", file=sys.stderr)
        return 1


def _make_agent_spec() -> AgentSpec:
    """Создать минимальный AgentSpec для ручной проверки gateway."""
    return AgentSpec(
        agent_id="smoke-outlook-agent",
        name="Smoke Outlook Agent",
        description="Ручная проверка Outlook COM tools",
        goal=AgentGoal(
            main_goal="Проверить безопасное чтение Outlook через ToolGateway",
            success_criteria=["Письма и календарь обработаны структурированно"],
            forbidden_actions=["Не отправлять письма", "Не изменять Outlook"],
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
                description="Финальный узел smoke-проверки",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            )
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def _print_result(title: str, result, list_key: str) -> None:
    """Вывести краткий результат read-only tool."""
    _print_basic_result(title, result)
    output_data = result.output_data or {}
    items = output_data.get(list_key, [])
    print(f"count: {output_data.get('count', 0)}")
    for index, item in enumerate(items[:5], start=1):
        if list_key == "messages":
            print(f"{index}. subject: {_truncate(item.get('subject'))}")
            print(f"   sender: {_truncate(item.get('sender'))}")
            print(f"   received_at: {_truncate(item.get('received_at'))}")
        else:
            print(f"{index}. subject: {_truncate(item.get('subject'))}")
            print(f"   start: {_truncate(item.get('start'))}")
            print(f"   end: {_truncate(item.get('end'))}")
            print(f"   location: {_truncate(item.get('location'))}")
            print(f"   organizer: {_truncate(item.get('organizer'))}")
    print()


def _print_basic_result(title: str, result) -> None:
    """Вывести базовые поля ToolCallResult."""
    print(f"== {title} ==")
    print(f"ok: {result.ok}")
    print(f"error_type: {result.error_type}")
    print(f"error_message: {result.error_message}")
    print(f"requires_human_approval: {result.requires_human_approval}")


def _truncate(value: object, limit: int = 120) -> str:
    """Ограничить вывод диагностических данных в консоль."""
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
