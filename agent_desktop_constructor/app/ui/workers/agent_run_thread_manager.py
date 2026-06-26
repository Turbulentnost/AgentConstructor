"""Менеджер QThread для фонового запуска агента."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.app.ui.workers.agent_run_worker import AgentRunWorker
from agent_desktop_constructor.core.models.agent_spec import AgentSpec


class AgentRunThreadManager(QObject):
    """Управляет одним активным фоновым запуском агента."""

    run_started = Signal(str)
    run_progress = Signal(str)
    run_completed = Signal(object)
    run_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Создать менеджер без активного потока."""
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: AgentRunWorker | None = None

    def start_agent_by_id(
        self,
        agent_id: str,
        service: AgentApplicationService,
    ) -> None:
        """Запустить сохранённого агента по agent_id."""
        self._start_worker(
            AgentRunWorker(
                service=service,
                agent_id=agent_id,
            )
        )

    def start_agent_spec(
        self,
        agent_spec: AgentSpec,
        service: AgentApplicationService,
    ) -> None:
        """Запустить переданный AgentSpec без сохранения."""
        self._start_worker(
            AgentRunWorker(
                service=service,
                agent_spec=agent_spec,
            )
        )

    def is_running(self) -> bool:
        """Вернуть True, если уже есть активный запуск."""
        return self._thread is not None

    def _start_worker(self, worker: AgentRunWorker) -> None:
        """Создать QThread, подключить worker и запустить."""
        if self.is_running():
            self.run_failed.emit("Уже есть активный запуск агента.")
            return

        thread = QThread()
        self._thread = thread
        self._worker = worker
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.started.connect(self.run_started)
        worker.progress.connect(self.run_progress)
        worker.completed.connect(self.run_completed)
        worker.failed.connect(self.run_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._cleanup)
        thread.finished.connect(thread.deleteLater)

        thread.start()

    def _cleanup(self) -> None:
        """Дождаться завершения потока и сбросить ссылки."""
        thread = self._thread
        if thread is not None:
            thread.wait(5000)
        self._thread = None
        self._worker = None

