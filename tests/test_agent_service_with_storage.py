"""Тесты AgentApplicationService с SQLite repositories."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.core.models.runtime_state import AgentRunStatus

TASK_CONTROL_REQUEST = "создай агента контроля поручений"


def make_container(tmp_path):
    """Собрать container с tmp SQLite и fake tools."""
    return build_application_container(
        AppConfig(
            run_mode=AppRunMode.FAKE,
            database_path=str(tmp_path / "agents.db"),
        )
    )


def test_create_agent_from_request_saves_agent(tmp_path) -> None:
    """service.create_agent_from_request(save=True) сохраняет агента."""
    container = make_container(tmp_path)

    agent_spec = container.agent_service.create_agent_from_request(
        TASK_CONTROL_REQUEST,
        save=True,
    )

    restored = container.agent_repository.get_agent(agent_spec.agent_id)
    assert restored == agent_spec


def test_list_agents_returns_agent_from_repository(tmp_path) -> None:
    """service.list_agents возвращает агента из repository."""
    container = make_container(tmp_path)
    agent_spec = container.agent_service.create_agent_from_request(TASK_CONTROL_REQUEST)

    agents = container.agent_service.list_agents()

    assert [agent.agent_id for agent in agents] == [agent_spec.agent_id]


def test_get_agent_returns_agent_from_repository(tmp_path) -> None:
    """service.get_agent возвращает AgentSpec из repository."""
    container = make_container(tmp_path)
    agent_spec = container.agent_service.create_agent_from_request(TASK_CONTROL_REQUEST)

    assert container.agent_service.get_agent(agent_spec.agent_id) == agent_spec


def test_run_agent_runs_saved_agent_and_persists_run(tmp_path) -> None:
    """service.run_agent запускает сохранённого агента и создаёт AgentRun."""
    container = make_container(tmp_path)
    agent_spec = container.agent_service.create_agent_from_request(TASK_CONTROL_REQUEST)

    state = container.agent_service.run_agent(agent_spec.agent_id)
    restored_state = container.run_repository.get_state(state.run_id)

    assert restored_state.status == AgentRunStatus.COMPLETED
    assert restored_state.tool_results


def test_run_agent_spec_works_without_save_agent(tmp_path) -> None:
    """service.run_agent_spec работает без предварительного save_agent."""
    container = make_container(tmp_path)
    agent_spec = container.agent_service.build_preview(TASK_CONTROL_REQUEST)

    state = container.agent_service.run_agent_spec(agent_spec)

    assert state.status == AgentRunStatus.COMPLETED
    assert container.agent_service.list_agents() == []


def test_audit_log_created_when_agent_saved(tmp_path) -> None:
    """Audit log создаётся при сохранении агента."""
    container = make_container(tmp_path)

    container.agent_service.create_agent_from_request(TASK_CONTROL_REQUEST, save=True)

    logs = container.audit_repository.list_logs()
    assert any(log["action"] == "agent.saved" for log in logs)

