"""Argparse entrypoint CLI для проверки ядра AgentConstructor."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from agent_desktop_constructor.app.cli import commands


def main(argv: Sequence[str] | None = None) -> int:
    """Разобрать argv и выполнить выбранную CLI-команду."""
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

    return parser


if __name__ == "__main__":
    raise SystemExit(main())

