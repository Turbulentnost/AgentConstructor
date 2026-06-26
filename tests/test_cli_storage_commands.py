"""Тесты CLI storage commands на tmp SQLite."""

import os
import re
import subprocess
import sys

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.cli import commands

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


def test_create_agent_prints_agent_id(monkeypatch, tmp_path, capsys) -> None:
    """create-agent создаёт агента и печатает agent_id."""
    configure_cli_env(monkeypatch, tmp_path)

    exit_code = commands.create_agent(TASK_CONTROL_REQUEST)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "agent_id:" in output
    assert "Агент контроля поручений" in output


def test_list_agents_shows_created_agent(monkeypatch, tmp_path, capsys) -> None:
    """list-agents показывает созданного агента."""
    configure_cli_env(monkeypatch, tmp_path)
    commands.create_agent(TASK_CONTROL_REQUEST)
    capsys.readouterr()

    exit_code = commands.list_agents()

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Агент контроля поручений" in output


def test_run_agent_creates_run(monkeypatch, tmp_path, capsys) -> None:
    """run-agent запускает агента в fake mode."""
    configure_cli_env(monkeypatch, tmp_path)
    commands.create_agent(TASK_CONTROL_REQUEST)
    agent_id = extract_value(capsys.readouterr().out, "agent_id")

    exit_code = commands.run_agent(agent_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Статус: completed" in output
    assert "outlook.search_mail" in output


def test_list_runs_shows_agent_run(monkeypatch, tmp_path, capsys) -> None:
    """list-runs показывает запуск агента."""
    configure_cli_env(monkeypatch, tmp_path)
    commands.create_agent(TASK_CONTROL_REQUEST)
    agent_id = extract_value(capsys.readouterr().out, "agent_id")
    commands.run_agent(agent_id)
    capsys.readouterr()

    exit_code = commands.list_runs(agent_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "status: completed" in output


def test_show_run_prints_saved_state(monkeypatch, tmp_path, capsys) -> None:
    """show-run показывает состояние запуска."""
    configure_cli_env(monkeypatch, tmp_path)
    commands.create_agent(TASK_CONTROL_REQUEST)
    agent_id = extract_value(capsys.readouterr().out, "agent_id")
    commands.run_agent(agent_id)
    run_id = extract_value(capsys.readouterr().out, "run_id")

    exit_code = commands.show_run(run_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Состояние запуска" in output
    assert "Статус: completed" in output


def test_resume_run_reports_when_run_is_not_waiting_for_human(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """resume-run даёт понятную ошибку для completed запуска."""
    configure_cli_env(monkeypatch, tmp_path)
    commands.create_agent(TASK_CONTROL_REQUEST)
    agent_id = extract_value(capsys.readouterr().out, "agent_id")
    commands.run_agent(agent_id)
    run_id = extract_value(capsys.readouterr().out, "run_id")

    exit_code = commands.resume_run(agent_id, run_id, approved=True)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Этот запуск не ожидает подтверждения человека." in output


def create_paused_run(tmp_path):
    """Создать сохранённого агента и paused run в tmp SQLite."""
    container = build_application_container(
        AppConfig(
            run_mode=AppRunMode.FAKE,
            database_path=str(tmp_path / "test_agents.db"),
        )
    )
    agent_spec = container.agent_service.create_agent_from_request(
        TASK_CONTROL_REQUEST,
        save=True,
    )
    state = container.agent_service.run_agent(
        agent_spec.agent_id,
        initial_variables={"force_human_review": True},
    )
    return agent_spec.agent_id, state.run_id


def test_resume_run_approve_continues_paused_run(monkeypatch, tmp_path, capsys) -> None:
    """resume-run --approve продолжает paused_for_human запуск."""
    configure_cli_env(monkeypatch, tmp_path)
    agent_id, run_id = create_paused_run(tmp_path)

    exit_code = commands.resume_run(agent_id, run_id, approved=True)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Статус: completed" in output


def test_resume_run_reject_continues_paused_run(monkeypatch, tmp_path, capsys) -> None:
    """resume-run --reject продолжает paused_for_human запуск по ветке отказа."""
    configure_cli_env(monkeypatch, tmp_path)
    agent_id, run_id = create_paused_run(tmp_path)

    exit_code = commands.resume_run(
        agent_id,
        run_id,
        approved=False,
        comment="Не подтверждаю",
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Статус: completed" in output


def test_cli_storage_commands_do_not_require_outlook(monkeypatch, tmp_path, capsys) -> None:
    """Storage CLI commands работают в fake mode без Outlook."""
    configure_cli_env(monkeypatch, tmp_path)

    assert commands.create_agent(TASK_CONTROL_REQUEST) == 0
    output = capsys.readouterr().out
    agent_id = extract_value(output, "agent_id")
    assert commands.list_agents() == 0
    assert commands.run_agent(agent_id) == 0


def test_list_agents_subprocess_smoke(tmp_path) -> None:
    """Хотя бы один smoke test проходит через scripts/run_agent_cli.py."""
    env = {
        **os.environ,
        "AGENT_APP_DATABASE_PATH": str(tmp_path / "test_agents.db"),
        "AGENT_APP_RUN_MODE": "fake",
    }
    completed = subprocess.run(
        [sys.executable, "scripts/run_agent_cli.py", "list-agents"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        env=env,
    )

    assert completed.returncode == 0
    assert "Сохранённых агентов пока нет." in completed.stdout

