"""Worker фонового запуска агента."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.core.models.agent_spec import AgentSpec


class AgentRunWorker(QObject):
    """QObject worker, выполняющий запуск агента вне UI-потока."""

    started = Signal(str)
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        service: AgentApplicationService,
        agent_id: str | None = None,
        agent_spec: AgentSpec | None = None,
        initial_variables: dict | None = None,
    ) -> None:
        """Создать worker для запуска по agent_id или AgentSpec."""
        super().__init__()
        self._service = service
        self._agent_id = agent_id
        self._agent_spec = agent_spec
        self._initial_variables = initial_variables

    @Slot()
    def run(self) -> None:
        """Выполнить запуск агента и отправить результат сигналами."""
        try:
            target = self._agent_id or (
                self._agent_spec.agent_id if self._agent_spec is not None else ""
            )
            self.started.emit(target)
            self.progress.emit("Агент запускается...")

            if self._agent_id is not None:
                state = self._service.run_agent(
                    self._agent_id,
                    self._initial_variables,
                )
            elif self._agent_spec is not None:
                state = self._service.run_agent_spec(
                    self._agent_spec,
                    self._initial_variables,
                )
            else:
                raise ValueError("Нужно указать agent_id или agent_spec")

            self.completed.emit(state)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

