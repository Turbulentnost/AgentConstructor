"""Тесты CLI-команд очереди подтверждений."""

from agent_desktop_constructor.app.cli import commands
from agent_desktop_constructor.app.core.bootstrap import build_application_container

TASK_CONTROL_REQUEST = "создай агента контроля поручений"


def configure_cli_env(monkeypatch, tmp_path) -> None:
    """Настроить CLI env на tmp SQLite и fake mode."""
    monkeypatch.setenv("AGENT_APP_DATABASE_PATH", str(tmp_path / "approvals.db"))
    monkeypatch.setenv("AGENT_APP_RUN_MODE", "fake")


def create_paused_approval(monkeypatch, tmp_path) -> str:
    """Создать paused запуск и вернуть approval_id."""
    configure_cli_env(monkeypatch, tmp_path)
    container = build_application_container()
    agent_spec = container.agent_service.create_agent_from_request(
        TASK_CONTROL_REQUEST,
        save=True,
    )
    state = container.agent_service.run_agent(
        agent_spec.agent_id,
        initial_variables={"force_human_review": True},
    )
    assert state.pending_human_approval is not None
    return state.pending_human_approval.approval_id


def test_list_approvals_shows_pending_approval(monkeypatch, tmp_path, capsys) -> None:
    """list-approvals показывает pending approval."""
    approval_id = create_paused_approval(monkeypatch, tmp_path)

    exit_code = commands.list_approvals()

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Ожидающие подтверждения" in output
    assert approval_id in output


def test_show_approval_prints_details(monkeypatch, tmp_path, capsys) -> None:
    """show-approval показывает детали."""
    approval_id = create_paused_approval(monkeypatch, tmp_path)

    exit_code = commands.show_approval(approval_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Подтверждение человека" in output
    assert "status: pending" in output
    assert "options:" in output


def test_approve_continues_run(monkeypatch, tmp_path, capsys) -> None:
    """approve <approval_id> продолжает запуск."""
    approval_id = create_paused_approval(monkeypatch, tmp_path)

    exit_code = commands.approve(approval_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Статус запуска: completed" in output


def test_reject_rejects_run(monkeypatch, tmp_path, capsys) -> None:
    """reject <approval_id> отклоняет запуск."""
    approval_id = create_paused_approval(monkeypatch, tmp_path)

    exit_code = commands.reject(approval_id, "Не подтверждаю")

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Статус запуска:" in output


def test_approval_cli_does_not_require_outlook_or_com(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    """Approval CLI работает в fake mode без Outlook и COM."""
    approval_id = create_paused_approval(monkeypatch, tmp_path)

    def fail_if_com_is_created(*args, **kwargs):
        raise AssertionError("COM worker не должен создаваться")

    monkeypatch.setattr(commands, "SubprocessComWorker", fail_if_com_is_created)

    assert commands.list_approvals() == 0
    assert commands.show_approval(approval_id) == 0
    assert commands.approve(approval_id) == 0


def test_approval_cli_does_not_send_real_email(monkeypatch, tmp_path, capsys) -> None:
    """Approval CLI в fake mode не отправляет реальные письма."""
    approval_id = create_paused_approval(monkeypatch, tmp_path)

    exit_code = commands.approve(approval_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SEND_DISABLED_FOR_SAFETY" not in output
    assert "sent: True" not in output

