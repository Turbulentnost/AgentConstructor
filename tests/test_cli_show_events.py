"""Тесты CLI show-events."""

import re

from agent_desktop_constructor.app.cli import commands
from agent_desktop_constructor.app.core.bootstrap import build_application_container

TASK_CONTROL_REQUEST = "Создай агента, который проверяет Outlook и находит поручения"


def configure_cli_env(monkeypatch, tmp_path) -> None:
    """Настроить CLI env на tmp SQLite и fake mode."""
    monkeypatch.setenv("AGENT_APP_DATABASE_PATH", str(tmp_path / "test_agents.db"))
    monkeypatch.setenv("AGENT_APP_RUN_MODE", "fake")


def extract_value(output: str, key: str) -> str:
    """Достать `key: value` из CLI output."""
    match = re.search(rf"{key}: ([^\s]+)", output)
    assert match is not None, output
    return match.group(1)


def create_and_run_agent(monkeypatch, tmp_path, capsys) -> tuple[str, str]:
    """Создать агента и вернуть agent_id/run_id."""
    configure_cli_env(monkeypatch, tmp_path)
    assert commands.create_agent(TASK_CONTROL_REQUEST) == 0
    agent_id = extract_value(capsys.readouterr().out, "agent_id")
    assert commands.run_agent(agent_id) == 0
    run_id = extract_value(capsys.readouterr().out, "run_id")
    return agent_id, run_id


def test_run_agent_creates_events(monkeypatch, tmp_path, capsys) -> None:
    """run-agent создаёт события выполнения."""
    _, run_id = create_and_run_agent(monkeypatch, tmp_path, capsys)

    container = build_application_container()
    events = container.run_event_repository.list_events(run_id)

    assert events
    assert events[0].event_type.value == "run_started"


def test_show_events_prints_events(monkeypatch, tmp_path, capsys) -> None:
    """show-events <run_id> показывает события."""
    _, run_id = create_and_run_agent(monkeypatch, tmp_path, capsys)

    exit_code = commands.show_events(run_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "События запуска" in output
    assert "run_started" in output
    assert "node_started" in output


def test_show_events_unknown_run_prints_clear_message(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """show-events для неизвестного run_id выводит понятное сообщение."""
    configure_cli_env(monkeypatch, tmp_path)

    exit_code = commands.show_events("unknown-run")

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Для этого запуска событий пока нет." in output


def test_show_events_cli_does_not_require_outlook_or_com(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """show-events работает в fake mode без Outlook и COM."""
    _, run_id = create_and_run_agent(monkeypatch, tmp_path, capsys)

    def fail_if_com_is_created(*args, **kwargs):
        raise AssertionError("COM worker не должен создаваться")

    monkeypatch.setattr(commands, "SubprocessComWorker", fail_if_com_is_created)

    assert commands.show_events(run_id) == 0

