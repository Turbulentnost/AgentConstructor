"""Тесты persistence очереди HumanApproval в SimpleAgentRuntime."""

from pathlib import Path

from agent_desktop_constructor.app.core.models.human_approval import HumanApprovalStatus
from agent_desktop_constructor.app.core.models.run_events import AgentRunEventType
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGraphNodeType,
)
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.storage.database import (
    create_engine_for_sqlite,
    create_session_factory,
    init_database,
)
from agent_desktop_constructor.storage.repositories import (
    AgentRunRepository,
    HumanApprovalRepository,
    RunEventRepository,
)
from tests.test_simple_runtime import (
    CountingTool,
    make_agent_spec,
    make_gateway,
    node,
    permission,
)


def make_repositories(
    tmp_path: Path,
) -> tuple[AgentRunRepository, HumanApprovalRepository, RunEventRepository]:
    """Создать SQLite repositories на tmp_path."""
    engine = create_engine_for_sqlite(tmp_path / "approvals.db")
    init_database(engine)
    session_factory = create_session_factory(engine)
    return (
        AgentRunRepository(session_factory),
        HumanApprovalRepository(session_factory),
        RunEventRepository(session_factory),
    )


def make_dangerous_agent_spec():
    """Создать AgentSpec с dangerous tool, требующим approval."""
    return make_agent_spec(
        [
            node(
                "dangerous",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.dangerous",
                next_on_success="final",
                next_on_error="final_failed",
            ),
            node("final", AgentGraphNodeType.FINAL),
            node("final_failed", AgentGraphNodeType.FINAL),
        ],
        [
            permission(
                "fake.dangerous",
                AgentActionLevel.DANGEROUS,
                requires_human_approval=True,
            )
        ],
    )


def make_runtime(
    run_repository: AgentRunRepository,
    approval_repository: HumanApprovalRepository,
    event_repository: RunEventRepository,
) -> SimpleAgentRuntime:
    """Создать runtime с fake dangerous tool."""
    tool = CountingTool(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )
    return SimpleAgentRuntime(
        make_gateway(tool),
        run_repository=run_repository,
        human_approval_repository=approval_repository,
        run_event_repository=event_repository,
    )


def test_runtime_persists_pending_human_approval(tmp_path: Path) -> None:
    """Runtime останавливается и сохраняет pending approval record."""
    run_repo, approval_repo, event_repo = make_repositories(tmp_path)
    runtime = make_runtime(run_repo, approval_repo, event_repo)

    state = runtime.run(make_dangerous_agent_spec(), run_id="run-1")

    records = approval_repo.list_pending()
    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert state.pending_human_approval is not None
    assert len(records) == 1
    assert records[0].approval_id == state.pending_human_approval.approval_id
    assert records[0].status == HumanApprovalStatus.PENDING


def test_resume_approved_updates_human_approval_record(tmp_path: Path) -> None:
    """resume approved обновляет HumanApprovalRecord в approved."""
    run_repo, approval_repo, event_repo = make_repositories(tmp_path)
    runtime = make_runtime(run_repo, approval_repo, event_repo)
    agent_spec = make_dangerous_agent_spec()
    state = runtime.run(agent_spec, run_id="run-1")
    assert state.pending_human_approval is not None
    approval_id = state.pending_human_approval.approval_id

    runtime.resume(agent_spec, state, approved=True)

    record = approval_repo.get_request(approval_id)
    assert record.status == HumanApprovalStatus.APPROVED
    assert record.answered_at is not None


def test_resume_approved_still_uses_tool_gateway(tmp_path: Path) -> None:
    """Подтверждение не обходит ToolGateway при продолжении запуска."""
    run_repo, approval_repo, event_repo = make_repositories(tmp_path)
    tool = CountingTool(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )
    gateway = make_gateway(tool)
    runtime = SimpleAgentRuntime(
        gateway,
        run_repository=run_repo,
        human_approval_repository=approval_repo,
        run_event_repository=event_repo,
    )
    agent_spec = make_dangerous_agent_spec()
    state = runtime.run(agent_spec, run_id="run-1")

    runtime.resume(agent_spec, state, approved=True)

    assert gateway.call_count == 2
    assert tool.execute_count == 1


def test_resume_rejected_updates_human_approval_record(tmp_path: Path) -> None:
    """resume rejected обновляет HumanApprovalRecord в rejected."""
    run_repo, approval_repo, event_repo = make_repositories(tmp_path)
    runtime = make_runtime(run_repo, approval_repo, event_repo)
    agent_spec = make_dangerous_agent_spec()
    state = runtime.run(agent_spec, run_id="run-1")
    assert state.pending_human_approval is not None
    approval_id = state.pending_human_approval.approval_id

    runtime.resume(agent_spec, state, approved=False, comment="Не подтверждаю")

    record = approval_repo.get_request(approval_id)
    assert record.status == HumanApprovalStatus.REJECTED
    assert record.comment == "Не подтверждаю"


def test_human_approval_events_are_written(tmp_path: Path) -> None:
    """RunEvent содержит human_approval_requested и human_approval_answered."""
    run_repo, approval_repo, event_repo = make_repositories(tmp_path)
    runtime = make_runtime(run_repo, approval_repo, event_repo)
    agent_spec = make_dangerous_agent_spec()
    state = runtime.run(agent_spec, run_id="run-1")

    runtime.resume(agent_spec, state, approved=True)

    event_types = [event.event_type for event in event_repo.list_events("run-1")]
    assert AgentRunEventType.HUMAN_APPROVAL_REQUESTED in event_types
    assert AgentRunEventType.HUMAN_APPROVAL_ANSWERED in event_types

