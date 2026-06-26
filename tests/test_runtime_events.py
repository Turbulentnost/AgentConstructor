"""Тесты событий SimpleAgentRuntime."""

from agent_desktop_constructor.app.core.models.run_events import (
    AgentRunEvent,
    AgentRunEventType,
)
from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentGraphNodeType,
)
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.core.models.tooling import ToolSideEffectLevel
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from tests.test_simple_runtime import (
    CountingTool,
    FailingTool,
    FakeRunRepository,
    make_agent_spec,
    make_gateway,
    node,
    permission,
)


class FakeRunEventRepository:
    """In-memory repository для проверки runtime events."""

    def __init__(self, fail_on_add: bool = False) -> None:
        """Создать fake repository."""
        self.fail_on_add = fail_on_add
        self.events: list[AgentRunEvent] = []

    def add_event(self, event: AgentRunEvent) -> None:
        """Сохранить событие или выбросить ошибку."""
        if self.fail_on_add:
            raise RuntimeError("event storage unavailable")
        self.events.append(event)


def event_types(repository: FakeRunEventRepository) -> list[AgentRunEventType]:
    """Вернуть типы записанных событий."""
    return [event.event_type for event in repository.events]


def make_runtime(
    tool: CountingTool | None = None,
    *,
    run_repository: FakeRunRepository | None = None,
    run_event_repository: FakeRunEventRepository | None = None,
) -> SimpleAgentRuntime:
    """Создать runtime с fake gateway и event repository."""
    return SimpleAgentRuntime(
        make_gateway(*(tool for tool in [tool] if tool is not None)),
        run_repository=run_repository,
        run_event_repository=run_event_repository,
    )


def test_runtime_writes_run_node_tool_checkpoint_and_completed_events() -> None:
    """Runtime пишет основные события успешного запуска."""
    tool = CountingTool()
    run_repository = FakeRunRepository()
    event_repository = FakeRunEventRepository()
    runtime = make_runtime(
        tool,
        run_repository=run_repository,
        run_event_repository=event_repository,
    )
    agent_spec = make_agent_spec(
        [
            node("validate", AgentGraphNodeType.VALIDATION, next_on_success="read"),
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    types = event_types(event_repository)
    assert state.status == AgentRunStatus.COMPLETED
    assert AgentRunEventType.RUN_STARTED in types
    assert AgentRunEventType.NODE_STARTED in types
    assert AgentRunEventType.NODE_COMPLETED in types
    assert AgentRunEventType.TOOL_CALL_STARTED in types
    assert AgentRunEventType.TOOL_CALL_COMPLETED in types
    assert AgentRunEventType.CHECKPOINT_SAVED in types
    assert AgentRunEventType.RUN_COMPLETED in types


def test_runtime_writes_tool_call_failed_event() -> None:
    """Если tool возвращает ошибку, Runtime пишет tool_call_failed."""
    tool = FailingTool()
    event_repository = FakeRunEventRepository()
    runtime = make_runtime(tool, run_event_repository=event_repository)
    agent_spec = make_agent_spec(
        [
            node(
                "read",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.read",
                next_on_success="final",
                next_on_error="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.read")],
    )

    runtime.run(agent_spec, run_id="run-1")

    assert AgentRunEventType.TOOL_CALL_FAILED in event_types(event_repository)


def test_runtime_writes_human_approval_requested_event() -> None:
    """Если HumanApproval нужен, Runtime пишет human_approval_requested."""
    tool = CountingTool(
        name="fake.write",
        side_effect_level=ToolSideEffectLevel.WRITE,
    )
    event_repository = FakeRunEventRepository()
    runtime = make_runtime(tool, run_event_repository=event_repository)
    agent_spec = make_agent_spec(
        [
            node(
                "write",
                AgentGraphNodeType.TOOL_CALL,
                tool_name="fake.write",
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [permission("fake.write", AgentActionLevel.WRITE)],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN
    assert AgentRunEventType.HUMAN_APPROVAL_REQUESTED in event_types(event_repository)


def test_runtime_writes_run_cancelled_event_after_rejected_human_review() -> None:
    """При отказе без error-ветки Runtime пишет run_cancelled."""
    event_repository = FakeRunEventRepository()
    runtime = make_runtime(run_event_repository=event_repository)
    agent_spec = make_agent_spec(
        [
            node(
                "review",
                AgentGraphNodeType.HUMAN_REVIEW,
                next_on_success="final",
            ),
            node("final", AgentGraphNodeType.FINAL),
        ],
        [],
    )
    state = runtime.run(
        agent_spec,
        run_id="run-1",
        initial_variables={"force_human_review": True},
    )

    state = runtime.resume(agent_spec, state, approved=False)

    assert state.status == AgentRunStatus.CANCELLED
    assert AgentRunEventType.HUMAN_APPROVAL_ANSWERED in event_types(event_repository)
    assert AgentRunEventType.RUN_CANCELLED in event_types(event_repository)


def test_runtime_writes_run_failed_event() -> None:
    """При failed-статусе Runtime пишет run_failed."""
    event_repository = FakeRunEventRepository()
    runtime = make_runtime(run_event_repository=event_repository)
    agent_spec = make_agent_spec(
        [node("final_failed", AgentGraphNodeType.FINAL)],
        [],
    )

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.FAILED
    assert AgentRunEventType.RUN_FAILED in event_types(event_repository)


def test_run_event_repository_error_does_not_crash_runtime() -> None:
    """Ошибка RunEventRepository не роняет Runtime."""
    event_repository = FakeRunEventRepository(fail_on_add=True)
    runtime = make_runtime(run_event_repository=event_repository)
    agent_spec = make_agent_spec([node("final", AgentGraphNodeType.FINAL)], [])

    state = runtime.run(agent_spec, run_id="run-1")

    assert state.status == AgentRunStatus.COMPLETED
    assert any("Ошибка записи события выполнения" in error for error in state.errors)

