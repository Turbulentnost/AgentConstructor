"""Тесты AgentApplicationService."""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)


TASK_CONTROL_REQUEST = "создай агента контроля поручений"


class FakeRuntime:
    """Runtime fake для проверки service orchestration."""

    def __init__(self) -> None:
        """Создать fake runtime."""
        self.run_called = False
        self.resume_called = False
        self.last_agent_spec: AgentSpec | None = None
        self.last_initial_variables: dict | None = None
        self.last_approved: bool | None = None
        self.last_comment: str | None = None

    def run(
        self,
        agent_spec: AgentSpec,
        initial_variables: dict | None = None,
    ) -> AgentRuntimeState:
        """Вернуть completed state без вызова tools."""
        self.run_called = True
        self.last_agent_spec = agent_spec
        self.last_initial_variables = initial_variables
        return AgentRuntimeState(
            run_id=str(uuid4()),
            agent_id=agent_spec.agent_id,
            status=AgentRunStatus.COMPLETED,
            current_node_id="final",
            variables=initial_variables or {},
        )

    def resume(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        approved: bool,
        comment: str | None = None,
    ) -> AgentRuntimeState:
        """Вернуть state и запомнить параметры resume."""
        self.resume_called = True
        self.last_agent_spec = agent_spec
        self.last_approved = approved
        self.last_comment = comment
        state.status = AgentRunStatus.COMPLETED
        return state


class FailingAuditRepository:
    """Audit repository, который падает при записи."""

    def add_log(self, action: str, details: dict, run_id: str | None = None) -> None:
        """Выбросить ошибку audit."""
        raise RuntimeError("audit unavailable")


def make_service(runtime: FakeRuntime | None = None) -> AgentApplicationService:
    """Создать service в memory-only режиме."""
    return AgentApplicationService(
        agent_builder=AgentBuilder(),
        runtime=runtime or FakeRuntime(),
    )


def test_build_preview_returns_agent_spec() -> None:
    """build_preview возвращает AgentSpec."""
    service = make_service()

    agent_spec = service.build_preview(TASK_CONTROL_REQUEST)

    assert isinstance(agent_spec, AgentSpec)


def test_build_preview_does_not_run_runtime() -> None:
    """build_preview не запускает Runtime."""
    runtime = FakeRuntime()
    service = make_service(runtime)

    service.build_preview(TASK_CONTROL_REQUEST)

    assert runtime.run_called is False


def test_create_agent_from_request_save_true_saves_agent() -> None:
    """create_agent_from_request(save=True) сохраняет агента."""
    service = make_service()

    agent_spec = service.create_agent_from_request(TASK_CONTROL_REQUEST, save=True)

    assert service.get_agent(agent_spec.agent_id) == agent_spec


def test_list_agents_returns_saved_agent() -> None:
    """list_agents возвращает сохранённого агента."""
    service = make_service()
    agent_spec = service.create_agent_from_request(TASK_CONTROL_REQUEST, save=True)

    agents = service.list_agents()

    assert [agent.agent_id for agent in agents] == [agent_spec.agent_id]


def test_get_agent_returns_agent() -> None:
    """get_agent возвращает агента из memory-only storage."""
    service = make_service()
    agent_spec = service.create_agent_from_request(TASK_CONTROL_REQUEST, save=True)

    restored = service.get_agent(agent_spec.agent_id)

    assert restored == agent_spec


def test_run_agent_runs_saved_agent() -> None:
    """run_agent запускает сохранённого агента."""
    runtime = FakeRuntime()
    service = make_service(runtime)
    agent_spec = service.create_agent_from_request(TASK_CONTROL_REQUEST, save=True)

    state = service.run_agent(agent_spec.agent_id, {"source": "test"})

    assert runtime.run_called is True
    assert state.status == AgentRunStatus.COMPLETED
    assert runtime.last_initial_variables == {"source": "test"}


def test_run_agent_requires_saved_agent() -> None:
    """run_agent запускает только уже сохранённого агента."""
    runtime = FakeRuntime()
    service = make_service(runtime)

    with pytest.raises(ValueError, match="не найден"):
        service.run_agent("missing-agent")

    assert runtime.run_called is False


def test_create_agent_from_request_save_false_does_not_save_agent() -> None:
    """create_agent_from_request(save=False) не сохраняет агента."""
    service = make_service()

    agent_spec = service.create_agent_from_request(TASK_CONTROL_REQUEST, save=False)

    assert service.list_agents() == []
    with pytest.raises(ValueError, match="не найден"):
        service.get_agent(agent_spec.agent_id)


def test_run_agent_spec_runs_without_saving() -> None:
    """run_agent_spec запускает AgentSpec без сохранения."""
    runtime = FakeRuntime()
    service = make_service(runtime)
    agent_spec = service.build_preview(TASK_CONTROL_REQUEST)

    state = service.run_agent_spec(agent_spec)

    assert runtime.run_called is True
    assert state.agent_id == agent_spec.agent_id
    assert service.list_agents() == []


def test_resume_run_calls_runtime_resume() -> None:
    """resume_run вызывает runtime.resume."""
    runtime = FakeRuntime()
    service = make_service(runtime)
    agent_spec = service.build_preview(TASK_CONTROL_REQUEST)
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.PAUSED_FOR_HUMAN,
        current_node_id="review",
    )

    resumed_state = service.resume_run(
        agent_spec,
        state,
        approved=True,
        comment="ok",
    )

    assert runtime.resume_called is True
    assert runtime.last_approved is True
    assert runtime.last_comment == "ok"
    assert resumed_state.status == AgentRunStatus.COMPLETED


def test_memory_only_mode_works_without_repository() -> None:
    """Memory-only режим работает без repository."""
    service = make_service()
    agent_spec = service.create_agent_from_request(TASK_CONTROL_REQUEST)

    assert service.get_agent(agent_spec.agent_id) == agent_spec
    assert service.memory_audit_logs


def test_audit_errors_do_not_crash_service() -> None:
    """Ошибки audit repository не роняют сервис."""
    service = AgentApplicationService(
        agent_builder=AgentBuilder(),
        runtime=FakeRuntime(),
        audit_repository=FailingAuditRepository(),
    )
    agent_spec = service.build_preview(TASK_CONTROL_REQUEST)

    service.save_agent(agent_spec)

    assert service.audit_warnings


def test_service_does_not_import_pyside6() -> None:
    """Сервис не импортирует PySide6."""
    source = inspect.getsource(AgentApplicationService)

    assert "PySide6" not in source


def test_service_does_not_import_pywin32() -> None:
    """Сервис не импортирует pywin32."""
    source = inspect.getsource(AgentApplicationService)

    assert "pythoncom" not in source
    assert "win32com" not in source


def test_service_does_not_call_tool_gateway_directly() -> None:
    """Сервис не вызывает ToolGateway напрямую."""
    source = inspect.getsource(AgentApplicationService)

    assert "ToolGateway" not in source
    assert "execute_tool" not in source


def test_service_does_not_call_com_directly() -> None:
    """Сервис не вызывает COM напрямую."""
    source = inspect.getsource(AgentApplicationService)

    assert "Dispatch(" not in source
    assert "SubprocessComWorker" not in source

