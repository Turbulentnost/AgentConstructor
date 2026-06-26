"""Тесты approval-методов AgentApplicationService."""

import pytest

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry

TASK_CONTROL_REQUEST = "создай агента контроля поручений"


def make_container(tmp_path):
    """Собрать container с tmp SQLite и fake tools."""
    return build_application_container(
        AppConfig(
            run_mode=AppRunMode.FAKE,
            database_path=str(tmp_path / "agents.db"),
        )
    )


def create_paused_run(container):
    """Создать сохранённого агента и paused approval."""
    agent_spec = container.agent_service.create_agent_from_request(
        TASK_CONTROL_REQUEST,
        save=True,
    )
    state = container.agent_service.run_agent(
        agent_spec.agent_id,
        initial_variables={"force_human_review": True},
    )
    assert state.pending_human_approval is not None
    return agent_spec, state, state.pending_human_approval.approval_id


def test_list_pending_approvals_returns_pending(tmp_path) -> None:
    """list_pending_approvals возвращает pending."""
    container = make_container(tmp_path)
    _, _, approval_id = create_paused_run(container)

    records = container.agent_service.list_pending_approvals()

    assert [record.approval_id for record in records] == [approval_id]


def test_get_approval_returns_record(tmp_path) -> None:
    """get_approval возвращает запись."""
    container = make_container(tmp_path)
    _, _, approval_id = create_paused_run(container)

    record = container.agent_service.get_approval(approval_id)

    assert record.approval_id == approval_id


def test_resume_run_by_approval_approved_continues_run(tmp_path) -> None:
    """resume_run_by_approval approved продолжает запуск."""
    container = make_container(tmp_path)
    _, _, approval_id = create_paused_run(container)

    state = container.agent_service.resume_run_by_approval(
        approval_id,
        approved=True,
    )

    assert state.status == AgentRunStatus.COMPLETED


def test_resume_run_by_approval_rejected_continues_error_path(tmp_path) -> None:
    """resume_run_by_approval rejected продолжает запуск по ветке отказа."""
    container = make_container(tmp_path)
    _, _, approval_id = create_paused_run(container)

    state = container.agent_service.resume_run_by_approval(
        approval_id,
        approved=False,
        comment="Не подтверждаю",
    )

    assert state.status in {AgentRunStatus.COMPLETED, AgentRunStatus.CANCELLED}


def test_resume_run_by_approval_fails_when_pending_state_mismatches(tmp_path) -> None:
    """resume_run_by_approval падает, если approval_id не совпадает со state."""
    container = make_container(tmp_path)
    _, state, approval_id = create_paused_run(container)
    assert state.pending_human_approval is not None
    changed_approval = state.pending_human_approval.model_copy(
        update={"approval_id": "different-approval"}
    )
    changed_state = state.model_copy(update={"pending_human_approval": changed_approval})
    container.run_repository.save_state(state.run_id, changed_state)

    with pytest.raises(ValueError, match="approval_id не соответствует"):
        container.agent_service.resume_run_by_approval(approval_id, approved=True)


def test_resume_run_by_approval_requires_storage() -> None:
    """Метод работает только при подключённом storage."""
    registry = ToolRegistry()
    service = AgentApplicationService(
        AgentBuilder(),
        SimpleAgentRuntime(ToolGateway(registry)),
    )

    with pytest.raises(ValueError, match="storage"):
        service.resume_run_by_approval("approval-1", approved=True)

