"""Тесты persistence поведения SimpleAgentRuntime."""

from pathlib import Path

from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.storage.database import (
    create_engine_for_sqlite,
    create_session_factory,
    init_database,
)
from agent_desktop_constructor.storage.repositories import AgentRunRepository
from agent_desktop_constructor.tools.fake_task_control_tools import (
    register_fake_task_control_tools,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


class CountingRunRepository:
    """Fake run repository со счётчиками create/save."""

    def __init__(self, fail_on_save: bool = False) -> None:
        """Создать fake repository."""
        self.create_count = 0
        self.save_count = 0
        self.fail_on_save = fail_on_save

    def create_run(self, agent_spec, initial_state) -> None:
        """Посчитать create_run."""
        self.create_count += 1

    def save_state(self, run_id, state) -> None:
        """Посчитать save_state или выбросить ошибку."""
        self.save_count += 1
        if self.fail_on_save:
            raise RuntimeError("save failed")


def make_runtime(run_repository=None) -> SimpleAgentRuntime:
    """Создать runtime с fake tools."""
    registry = ToolRegistry()
    register_fake_task_control_tools(registry)
    return SimpleAgentRuntime(ToolGateway(registry), run_repository=run_repository)


def make_agent_spec():
    """Создать task-control AgentSpec."""
    return AgentBuilder().build_from_request("создай агента контроля поручений")


def make_run_repository(tmp_path: Path) -> AgentRunRepository:
    """Создать SQLite AgentRunRepository на tmp_path."""
    engine = create_engine_for_sqlite(tmp_path / "agents.db")
    init_database(engine)
    return AgentRunRepository(create_session_factory(engine))


def test_runtime_persists_run_and_final_state_to_sqlite(tmp_path: Path) -> None:
    """Runtime создаёт run и сохраняет финальный completed state."""
    run_repository = make_run_repository(tmp_path)
    runtime = make_runtime(run_repository)
    agent_spec = make_agent_spec()

    state = runtime.run(agent_spec)
    restored_state = run_repository.get_state(state.run_id)

    assert restored_state.status == AgentRunStatus.COMPLETED
    assert restored_state.run_id == state.run_id
    assert restored_state.tool_results
    assert restored_state.variables["tool_outputs"]["outlook.search_mail"]
    assert restored_state.step_counter == state.step_counter


def test_create_run_called_once_and_save_state_multiple_times() -> None:
    """create_run вызывается один раз, save_state — после шагов."""
    run_repository = CountingRunRepository()
    runtime = make_runtime(run_repository)

    runtime.run(make_agent_spec())

    assert run_repository.create_count == 1
    assert run_repository.save_count > 1


def test_resume_does_not_call_create_run_second_time() -> None:
    """resume не вызывает create_run повторно."""
    run_repository = CountingRunRepository()
    runtime = make_runtime(run_repository)
    agent_spec = make_agent_spec()
    state = runtime.run(agent_spec, initial_variables={"force_human_review": True})

    runtime.resume(agent_spec, state, approved=True)

    assert run_repository.create_count == 1


def test_resume_persists_updated_state_to_sqlite(tmp_path: Path) -> None:
    """resume сохраняет обновлённое состояние в SQLite без нового create_run."""
    run_repository = make_run_repository(tmp_path)
    runtime = make_runtime(run_repository)
    agent_spec = make_agent_spec()
    state = runtime.run(agent_spec, initial_variables={"force_human_review": True})

    resumed_state = runtime.resume(agent_spec, state, approved=True)
    restored_state = run_repository.get_state(resumed_state.run_id)

    assert restored_state.run_id == state.run_id
    assert restored_state.status == AgentRunStatus.COMPLETED
    assert restored_state.pending_human_approval is None


def test_save_state_error_is_added_to_state_errors() -> None:
    """Ошибка save_state добавляется в state.errors и не роняет runtime."""
    run_repository = CountingRunRepository(fail_on_save=True)
    runtime = make_runtime(run_repository)

    state = runtime.run(make_agent_spec())

    assert any("Ошибка сохранения состояния" in error for error in state.errors)

