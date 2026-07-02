"""Argparse entrypoint CLI для проверки ядра AgentConstructor."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from agent_desktop_constructor.app.cli import commands
from agent_desktop_constructor.app.core.config import load_dotenv_into_environ


def main(argv: Sequence[str] | None = None) -> int:
    """Разобрать argv и выполнить выбранную CLI-команду."""
    load_dotenv_into_environ()
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "build-agent":
            return commands.build_agent(args.user_request)
        if args.command == "run-fake":
            return commands.run_fake(args.user_request)
        if args.command == "run-outlook-readonly":
            return commands.run_outlook_readonly(args.user_request)
        if args.command == "diagnose-outlook":
            return commands.diagnose_outlook()
        if args.command == "test-send-block":
            return commands.test_send_block()
        if args.command == "create-agent":
            return commands.create_agent(args.user_request)
        if args.command == "list-agents":
            return commands.list_agents()
        if args.command == "run-agent":
            return commands.run_agent(args.agent_id)
        if args.command == "list-runs":
            return commands.list_runs(args.agent_id)
        if args.command == "show-run":
            return commands.show_run(args.run_id)
        if args.command == "show-events":
            return commands.show_events(args.run_id, verbose=args.verbose)
        if args.command == "list-approvals":
            return commands.list_approvals()
        if args.command == "show-approval":
            return commands.show_approval(args.approval_id)
        if args.command == "approve":
            return commands.approve(args.approval_id)
        if args.command == "reject":
            return commands.reject(args.approval_id, args.comment)
        if args.command == "resume-run":
            return commands.resume_run(
                args.agent_id,
                args.run_id,
                approved=args.approve,
                comment=args.reject,
            )
    except Exception as exc:
        print(f"Ошибка выполнения CLI: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """Создать argparse parser с командами CLI."""
    parser = argparse.ArgumentParser(
        prog="run_agent_cli.py",
        description="CLI для проверки ядра AgentConstructor без desktop UI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_agent_parser = subparsers.add_parser(
        "build-agent",
        help="Собрать AgentSpec из текстового запроса без запуска инструментов.",
    )
    build_agent_parser.add_argument("user_request")

    run_fake_parser = subparsers.add_parser(
        "run-fake",
        help="Запустить агента на fake tools без Outlook.",
    )
    run_fake_parser.add_argument("user_request")

    run_outlook_parser = subparsers.add_parser(
        "run-outlook-readonly",
        help="Запустить агента на Outlook COM read-only tools через subprocess.",
    )
    run_outlook_parser.add_argument("user_request")

    subparsers.add_parser(
        "diagnose-outlook",
        help="Проверить доступность Outlook COM/MAPI через worker diagnostics.",
    )
    subparsers.add_parser(
        "test-send-block",
        help="Проверить, что email.send блокируется gateway и Outlook worker.",
    )

    create_agent_parser = subparsers.add_parser(
        "create-agent",
        help="Создать и сохранить AgentSpec в SQLite.",
    )
    create_agent_parser.add_argument("user_request")

    subparsers.add_parser(
        "list-agents",
        help="Показать сохранённых агентов из SQLite.",
    )

    run_agent_parser = subparsers.add_parser(
        "run-agent",
        help="Запустить сохранённого агента по agent_id.",
    )
    run_agent_parser.add_argument("agent_id")

    list_runs_parser = subparsers.add_parser(
        "list-runs",
        help="Показать сохранённые запуски агента.",
    )
    list_runs_parser.add_argument("agent_id")

    show_run_parser = subparsers.add_parser(
        "show-run",
        help="Показать подробное состояние запуска.",
    )
    show_run_parser.add_argument("run_id")

    show_events_parser = subparsers.add_parser(
        "show-events",
        help="Показать журнал событий запуска.",
    )
    show_events_parser.add_argument("run_id")
    show_events_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Показать краткое содержимое details.",
    )

    subparsers.add_parser(
        "list-approvals",
        help="Показать очередь ожидающих подтверждений.",
    )

    show_approval_parser = subparsers.add_parser(
        "show-approval",
        help="Показать подробности запроса подтверждения.",
    )
    show_approval_parser.add_argument("approval_id")

    approve_parser = subparsers.add_parser(
        "approve",
        help="Подтвердить запрос и продолжить запуск.",
    )
    approve_parser.add_argument("approval_id")

    reject_parser = subparsers.add_parser(
        "reject",
        help="Отклонить запрос и продолжить запуск.",
    )
    reject_parser.add_argument("approval_id")
    reject_parser.add_argument("comment")

    resume_run_parser = subparsers.add_parser(
        "resume-run",
        help="Продолжить запуск после HumanApproval.",
    )
    resume_run_parser.add_argument("agent_id")
    resume_run_parser.add_argument("run_id")
    approval_group = resume_run_parser.add_mutually_exclusive_group(required=True)
    approval_group.add_argument("--approve", action="store_true")
    approval_group.add_argument("--reject")

    return parser


if __name__ == "__main__":
    raise SystemExit(main())

