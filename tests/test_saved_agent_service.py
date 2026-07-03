"""Тесты сервисных методов каталога агентов: run_saved / resume / delete."""

import pytest

from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)


class RecordingRuntime:
    """Runtime, фиксирующий переданные callbacks и variables."""

    def __init__(self) -> None:
        self.progress_cb = None
        self.cancel_cb = None
        self.run_variables = None
        self.resume_calls: list[str] = []

    def set_progress_callback(self, callback) -> None:
        self.progress_cb = callback

    def set_cancel_callback(self, callback) -> None:
        self.cancel_cb = callback

    def run(self, agent_spec, initial_variables=None):
        self.run_variables = initial_variables
        if self.progress_cb is not None:
            self.progress_cb("шаг 1")
        return AgentRuntimeState(
            run_id="run-1",
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.COMPLETED,
        )

    def resume_with_human_input(self, agent_spec, state, human_message, approved):
        self.resume_calls.append(human_message)
        return AgentRuntimeState(
            run_id=state.run_id,
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.COMPLETED,
        )


def _service_with_saved_agent() -> tuple[AgentApplicationService, str, RecordingRuntime]:
    runtime = RecordingRuntime()
    service = AgentApplicationService(agent_builder=AgentBuilder(), runtime=runtime)
    spec = AgentBuilder().build_from_request("Найди совещания в Outlook")
    saved = service.finalize_and_save_agent(spec, "Найди совещания в Outlook")
    return service, saved.agent_id, runtime


def test_run_saved_agent_streams_progress_and_uses_saved_spec() -> None:
    """run_saved_agent прокидывает progress и запускает по сохранённому графу."""
    service, agent_id, runtime = _service_with_saved_agent()
    messages: list[str] = []

    state = service.run_saved_agent(
        agent_id,
        progress_callback=messages.append,
        cancel_callback=lambda: False,
    )

    assert state.status == AgentRunStatus.COMPLETED
    assert messages == ["шаг 1"]
    assert runtime.run_variables is not None
    # После запуска callbacks должны быть очищены.
    assert runtime.progress_cb is None
    assert runtime.cancel_cb is None


def test_resume_saved_agent_after_human_continues() -> None:
    """resume_saved_agent_after_human продолжает работу с ответом человека."""
    service, agent_id, runtime = _service_with_saved_agent()
    spec = service.get_agent(agent_id)
    paused = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_id,
        status=AgentRunStatus.PAUSED_FOR_HUMAN,
    )

    state = service.resume_saved_agent_after_human(spec, paused, "Готово")

    assert state.status == AgentRunStatus.COMPLETED
    assert runtime.resume_calls == ["Готово"]


def test_delete_agent_removes_from_catalog() -> None:
    """delete_agent убирает агента из каталога."""
    service, agent_id, _ = _service_with_saved_agent()

    service.delete_agent(agent_id)

    with pytest.raises(ValueError):
        service.get_agent(agent_id)
