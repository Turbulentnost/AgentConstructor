"""Тесты AgentRunThreadManager."""

from __future__ import annotations

import os
import time

import pytest

from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from agent_desktop_constructor.app.ui.workers.agent_run_thread_manager import (  # noqa: E402
    AgentRunThreadManager,
)


@pytest.fixture(scope="session")
def qt_app():
    """Создать QApplication для manager-тестов."""
    return QApplication.instance() or QApplication([])


class SlowRunService:
    """Fake service с небольшой задержкой."""

    def __init__(self, delay: float = 0.02) -> None:
        """Создать fake service."""
        self.delay = delay
        self.calls: list[str] = []
        self.state = AgentRuntimeState(
            run_id="run-1",
            agent_id="agent-1",
            status=AgentRunStatus.COMPLETED,
        )

    def run_agent(self, agent_id: str, initial_variables: dict | None = None):
        """Имитация запуска агента."""
        self.calls.append(f"run_agent:{agent_id}")
        time.sleep(self.delay)
        return self.state


def wait_until_finished(manager: AgentRunThreadManager, timeout_ms: int = 1000) -> None:
    """Дождаться завершения manager или timeout."""
    loop = QEventLoop()

    def stop_if_finished() -> None:
        if not manager.is_running():
            loop.quit()

    poll_timer = QTimer()
    poll_timer.setInterval(5)
    poll_timer.timeout.connect(stop_if_finished)
    poll_timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    poll_timer.stop()


def test_thread_manager_rejects_second_run_while_first_is_active(qt_app) -> None:
    """ThreadManager не запускает второй запуск параллельно."""
    service = SlowRunService(delay=0.05)
    manager = AgentRunThreadManager()
    failures: list[str] = []
    manager.run_failed.connect(failures.append)

    manager.start_agent_by_id("agent-1", service)
    manager.start_agent_by_id("agent-2", service)
    wait_until_finished(manager)

    assert "Уже есть активный запуск агента." in failures
    assert service.calls == ["run_agent:agent-1"]


def test_thread_manager_cleans_up_after_completion(qt_app) -> None:
    """ThreadManager корректно завершает поток."""
    service = SlowRunService()
    manager = AgentRunThreadManager()
    completed: list[object] = []
    manager.run_completed.connect(completed.append)

    manager.start_agent_by_id("agent-1", service)
    wait_until_finished(manager)

    assert completed == [service.state]
    assert manager.is_running() is False

