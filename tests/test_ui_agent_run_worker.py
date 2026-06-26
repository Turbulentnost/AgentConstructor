"""Тесты AgentRunWorker."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from tests.test_storage import make_agent_spec

pytest.importorskip("PySide6")

from agent_desktop_constructor.app.ui.workers.agent_run_worker import (  # noqa: E402
    AgentRunWorker,
)


class FakeRunService:
    """Fake service для AgentRunWorker."""

    def __init__(self, fail: bool = False) -> None:
        """Создать fake service."""
        self.fail = fail
        self.calls: list[str] = []
        self.state = AgentRuntimeState(
            run_id="run-1",
            agent_id="agent-1",
            status=AgentRunStatus.COMPLETED,
        )

    def run_agent(self, agent_id: str, initial_variables: dict | None = None):
        """Зафиксировать run_agent."""
        self.calls.append(f"run_agent:{agent_id}:{initial_variables}")
        if self.fail:
            raise RuntimeError("run failed")
        return self.state

    def run_agent_spec(self, agent_spec, initial_variables: dict | None = None):
        """Зафиксировать run_agent_spec."""
        self.calls.append(f"run_agent_spec:{agent_spec.agent_id}:{initial_variables}")
        if self.fail:
            raise RuntimeError("run failed")
        return self.state


def test_worker_calls_service_run_agent_for_agent_id() -> None:
    """AgentRunWorker вызывает service.run_agent при agent_id."""
    service = FakeRunService()
    completed = []
    worker = AgentRunWorker(service, agent_id="agent-1", initial_variables={"x": 1})
    worker.completed.connect(completed.append)

    worker.run()

    assert service.calls == ["run_agent:agent-1:{'x': 1}"]
    assert completed == [service.state]


def test_worker_calls_service_run_agent_spec_for_agent_spec() -> None:
    """AgentRunWorker вызывает service.run_agent_spec при agent_spec."""
    service = FakeRunService()
    agent_spec = make_agent_spec()
    completed = []
    worker = AgentRunWorker(service, agent_spec=agent_spec)
    worker.completed.connect(completed.append)

    worker.run()

    assert service.calls == [f"run_agent_spec:{agent_spec.agent_id}:None"]
    assert completed == [service.state]


def test_worker_emits_completed_on_success() -> None:
    """При успехе worker emits completed."""
    service = FakeRunService()
    completed = []
    failed = []
    worker = AgentRunWorker(service, agent_id="agent-1")
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert completed == [service.state]
    assert failed == []


def test_worker_emits_failed_on_error() -> None:
    """При ошибке worker emits failed."""
    service = FakeRunService(fail=True)
    completed = []
    failed = []
    worker = AgentRunWorker(service, agent_id="agent-1")
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert completed == []
    assert failed == ["run failed"]


@pytest.mark.parametrize("forbidden", ["pywin32", "pythoncom", "win32com", "COM"])
def test_worker_source_does_not_import_com_modules(forbidden: str) -> None:
    """Worker не импортирует pywin32/COM."""
    source = Path(
        "agent_desktop_constructor/app/ui/workers/agent_run_worker.py"
    ).read_text(encoding="utf-8")

    assert forbidden not in source

