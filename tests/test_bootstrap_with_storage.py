"""Тесты bootstrap-а с реальным SQLite storage на tmp_path."""

from sqlalchemy import inspect

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeOutlookSearchMailTool,
)
from agent_desktop_constructor.workers.subprocess_com_worker import SubprocessComWorker


def make_config(tmp_path, run_mode: AppRunMode = AppRunMode.FAKE) -> AppConfig:
    """Создать config с tmp SQLite."""
    return AppConfig(run_mode=run_mode, database_path=str(tmp_path / "agents.db"))


def test_build_application_container_creates_sqlite_file(tmp_path) -> None:
    """build_application_container создаёт SQLite файл."""
    db_path = tmp_path / "agents.db"

    build_application_container(make_config(tmp_path))

    assert db_path.exists()


def test_container_repositories_are_not_none(tmp_path) -> None:
    """Container содержит repositories и session_factory."""
    container = build_application_container(make_config(tmp_path))

    assert container.agent_repository is not None
    assert container.run_repository is not None
    assert container.audit_repository is not None
    assert container.agent_service is not None
    assert container.session_factory is not None


def test_init_database_creates_tables(tmp_path) -> None:
    """init_database создаёт таблицы storage."""
    container = build_application_container(make_config(tmp_path))

    engine = container.session_factory.kw["bind"]
    table_names = set(inspect(engine).get_table_names())

    assert {"agents", "agent_runs", "audit_logs", "tool_call_logs"}.issubset(
        table_names
    )


def test_bootstrap_does_not_call_tools(tmp_path, monkeypatch) -> None:
    """Bootstrap не вызывает tool.execute."""

    def fail_execute(self, input_data):
        raise AssertionError("tool.execute не должен вызываться при bootstrap")

    monkeypatch.setattr(FakeOutlookSearchMailTool, "execute", fail_execute)

    container = build_application_container(make_config(tmp_path))

    assert container.tool_registry.has_tool("outlook.search_mail")


def test_bootstrap_does_not_call_com(tmp_path, monkeypatch) -> None:
    """Bootstrap не вызывает COM worker execute."""

    def fail_execute(self, task):
        raise AssertionError("COM worker execute не должен вызываться при bootstrap")

    monkeypatch.setattr(SubprocessComWorker, "execute", fail_execute)

    container = build_application_container(
        make_config(tmp_path, AppRunMode.OUTLOOK_READONLY)
    )

    assert container.tool_registry.has_tool("outlook.read_calendar")


def test_outlook_readonly_container_builds_without_reading_outlook(tmp_path) -> None:
    """outlook_readonly container создаётся без чтения Outlook."""
    container = build_application_container(
        make_config(tmp_path, AppRunMode.OUTLOOK_READONLY)
    )

    assert container.tool_registry.has_tool("outlook.search_mail")

