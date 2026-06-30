"""Тесты AgentApplicationService.create_validate_and_run_once."""

from agent_desktop_constructor.app.core.models.agent_validation import (
    AgentValidationResult,
    AgentValidationStatus,
)
from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)


class FakeRuntime:
    """Runtime, который не должен вызываться повторно."""

    def __init__(self) -> None:
        self.run_calls = 0

    def run(self, agent_spec, initial_variables=None):
        """Зафиксировать неожиданный запуск."""
        self.run_calls += 1
        return AgentRuntimeState(
            run_id="unexpected-run",
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.COMPLETED,
        )


class RaisingBuilder:
    """Builder, имитирующий timeout LLM Planner-а."""

    tools_catalog = AgentBuilder().tools_catalog

    def build_from_request(self, user_request: str):
        """Выбросить timeout."""
        raise TimeoutError("timed out")


class FakeValidationService:
    """Validation service stub."""

    def __init__(
        self,
        status: AgentValidationStatus,
        state_status: AgentRunStatus = AgentRunStatus.COMPLETED,
    ) -> None:
        self.status = status
        self.calls: list[str] = []
        self.state = AgentRuntimeState(
            run_id="validation-run",
            agent_id="agent-placeholder",
            status=state_status,
            variables={"final_message": "Проверка прошла"},
        )

    def validate_agent(self, agent_spec, user_request: str):
        """Вернуть validation result."""
        self.calls.append(user_request)
        self.state.agent_id = agent_spec.agent_id
        return AgentValidationResult(
            agent_id=agent_spec.agent_id,
            status=self.status,
            run_id=self.state.run_id,
            errors=[] if self.status == AgentValidationStatus.PASSED else ["bad"],
            warnings=[],
            summary=self.status.value,
            suggested_fixes=[],
        )

    def get_validation_state(self, run_id: str | None):
        """Вернуть состояние пробного запуска."""
        if run_id == self.state.run_id:
            return self.state
        return None


def test_create_validate_and_run_once_saves_and_returns_validation_state() -> None:
    """При passed сервис сохраняет агента и возвращает проверочный state."""
    runtime = FakeRuntime()
    validation_service = FakeValidationService(AgentValidationStatus.PASSED)
    service = AgentApplicationService(
        agent_builder=AgentBuilder(),
        runtime=runtime,
        agent_validation_service=validation_service,
    )

    agent_spec, validation, state = service.create_validate_and_run_once("Найди совещания")

    assert validation.status == AgentValidationStatus.PASSED
    assert state is validation_service.state
    assert runtime.run_calls == 0
    assert service.get_agent(agent_spec.agent_id) == agent_spec


def test_create_validate_and_run_once_does_not_save_failed_agent() -> None:
    """При failed агент не сохраняется и повторный run не вызывается."""
    runtime = FakeRuntime()
    validation_service = FakeValidationService(
        AgentValidationStatus.FAILED,
        AgentRunStatus.FAILED,
    )
    service = AgentApplicationService(
        agent_builder=AgentBuilder(),
        runtime=runtime,
        agent_validation_service=validation_service,
    )

    agent_spec, validation, state = service.create_validate_and_run_once("Найди совещания")

    assert validation.status == AgentValidationStatus.FAILED
    assert state is validation_service.state
    assert runtime.run_calls == 0
    try:
        service.get_agent(agent_spec.agent_id)
    except ValueError:
        saved = False
    else:
        saved = True
    assert saved is False


def test_create_validate_and_run_once_returns_waiting_state() -> None:
    """needs_human/needs_credentials возвращают состояние ожидания."""
    validation_service = FakeValidationService(
        AgentValidationStatus.NEEDS_HUMAN,
        AgentRunStatus.PAUSED_FOR_HUMAN,
    )
    service = AgentApplicationService(
        agent_builder=AgentBuilder(),
        runtime=FakeRuntime(),
        agent_validation_service=validation_service,
    )

    _, validation, state = service.create_validate_and_run_once("Найди совещания")

    assert validation.status == AgentValidationStatus.NEEDS_HUMAN
    assert state is validation_service.state


def test_create_validate_and_run_once_returns_failed_validation_on_builder_timeout() -> None:
    """Timeout LLM Planner-а возвращается как ValidationResult, а не exception."""
    runtime = FakeRuntime()
    validation_service = FakeValidationService(AgentValidationStatus.PASSED)
    service = AgentApplicationService(
        agent_builder=RaisingBuilder(),
        runtime=runtime,
        agent_validation_service=validation_service,
    )

    agent_spec, validation, state = service.create_validate_and_run_once(
        "Найди совещания"
    )

    assert agent_spec.agent_id
    assert validation.status == AgentValidationStatus.FAILED
    assert validation.errors == ["timed out"]
    assert validation.run_id is None
    assert state is None
    assert validation_service.calls == []
    assert runtime.run_calls == 0

