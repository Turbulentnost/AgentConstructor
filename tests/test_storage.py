"""Тесты локального SQLite-хранилища."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agent_desktop_constructor.core.models.agent_spec import (
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
)
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.storage.database import (
    create_engine_for_sqlite,
    create_session_factory,
    init_database,
)
from agent_desktop_constructor.storage.entities import (
    AgentEntity,
    AgentRunEntity,
    AuditLogEntity,
    ToolCallLogEntity,
)
from agent_desktop_constructor.storage.repositories import (
    AgentRepository,
    AgentRunRepository,
    AuditLogRepository,
    ToolCallLogRepository,
)


def make_agent_spec(
    *,
    agent_id: str = "agent-1",
    name: str = "Агент контроля поручений",
    description: str = "Русское описание агента",
) -> AgentSpec:
    """Создать валидный AgentSpec для storage-тестов."""
    return AgentSpec(
        agent_id=agent_id,
        name=name,
        description=description,
        goal=AgentGoal(
            main_goal="Найти поручения и сформировать отчёт",
            success_criteria=["Отчёт сформирован"],
            forbidden_actions=["Не отправлять письма без подтверждения"],
        ),
        data_requirements=[],
        tools=[],
        graph_nodes=[
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Завершить",
                description="Финальный узел",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            )
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def make_state(
    *,
    run_id: str = "run-1",
    agent_id: str = "agent-1",
    status: AgentRunStatus = AgentRunStatus.CREATED,
    current_node_id: str | None = None,
) -> AgentRuntimeState:
    """Создать валидное состояние запуска для storage-тестов."""
    return AgentRuntimeState(
        run_id=run_id,
        agent_id=agent_id,
        status=status,
        current_node_id=current_node_id,
    )


def make_storage(
    tmp_path: Path,
) -> tuple[Engine, sessionmaker[Session]]:
    """Создать временную SQLite-базу и фабрику сессий."""
    engine = create_engine_for_sqlite(tmp_path / "agents-test.db")
    init_database(engine)
    return engine, create_session_factory(engine)


def test_init_database_creates_tables(tmp_path: Path) -> None:
    """init_database создает таблицы storage-слоя."""
    engine, _ = make_storage(tmp_path)

    table_names = set(inspect(engine).get_table_names())

    assert {
        "agents",
        "agent_runs",
        "tool_call_logs",
        "audit_logs",
    }.issubset(table_names)


def test_create_engine_for_sqlite_creates_parent_directory(tmp_path: Path) -> None:
    """create_engine_for_sqlite создает parent directory для файла базы."""
    db_path = tmp_path / "nested" / "storage" / "agents.db"

    engine = create_engine_for_sqlite(db_path)
    init_database(engine)

    assert db_path.parent.exists()


def test_agent_repository_save_agent_stores_agent_spec(tmp_path: Path) -> None:
    """AgentRepository.save_agent сохраняет AgentSpec."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRepository(session_factory)

    repo.save_agent(make_agent_spec())

    with session_factory() as session:
        entity = session.get(AgentEntity, "agent-1")
        assert entity is not None
        assert entity.name == "Агент контроля поручений"


def test_agent_repository_get_agent_restores_agent_spec(tmp_path: Path) -> None:
    """AgentRepository.get_agent восстанавливает AgentSpec."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRepository(session_factory)
    agent_spec = make_agent_spec()

    repo.save_agent(agent_spec)
    restored = repo.get_agent("agent-1")

    assert restored == agent_spec


def test_agent_repository_list_agents_returns_saved_agent(tmp_path: Path) -> None:
    """AgentRepository.list_agents возвращает сохраненного агента."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRepository(session_factory)

    repo.save_agent(make_agent_spec())

    assert [agent.agent_id for agent in repo.list_agents()] == ["agent-1"]


def test_repeated_save_agent_updates_existing_row(tmp_path: Path) -> None:
    """Повторный save_agent обновляет запись, а не создает дубль."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRepository(session_factory)

    repo.save_agent(make_agent_spec())
    repo.save_agent(make_agent_spec(name="Обновленный агент"))

    with session_factory() as session:
        agents = session.scalars(select(AgentEntity)).all()
        assert len(agents) == 1
        assert agents[0].name == "Обновленный агент"


def test_agent_run_repository_create_run_creates_run(tmp_path: Path) -> None:
    """AgentRunRepository.create_run создает запуск."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRunRepository(session_factory)

    repo.create_run(make_agent_spec(), make_state())

    with session_factory() as session:
        entity = session.get(AgentRunEntity, "run-1")
        assert entity is not None
        assert entity.status == AgentRunStatus.CREATED.value


def test_agent_run_repository_get_state_restores_state(tmp_path: Path) -> None:
    """AgentRunRepository.get_state восстанавливает AgentRuntimeState."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRunRepository(session_factory)
    state = make_state(current_node_id="start")

    repo.create_run(make_agent_spec(), state)
    restored = repo.get_state("run-1")

    assert restored == state


def test_agent_run_repository_save_state_updates_status_and_node(
    tmp_path: Path,
) -> None:
    """AgentRunRepository.save_state обновляет статус и current_node_id."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRunRepository(session_factory)
    repo.create_run(make_agent_spec(), make_state())
    updated_state = make_state(
        status=AgentRunStatus.RUNNING,
        current_node_id="read_mail",
    )

    repo.save_state("run-1", updated_state)

    with session_factory() as session:
        entity = session.get(AgentRunEntity, "run-1")
        assert entity is not None
        assert entity.status == AgentRunStatus.RUNNING.value
        assert entity.current_node_id == "read_mail"


def test_finished_at_is_set_for_completed_status(tmp_path: Path) -> None:
    """При completed устанавливается finished_at."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRunRepository(session_factory)
    repo.create_run(make_agent_spec(), make_state())
    completed_state = make_state(status=AgentRunStatus.COMPLETED)

    repo.save_state("run-1", completed_state)

    with session_factory() as session:
        entity = session.get(AgentRunEntity, "run-1")
        assert entity is not None
        assert entity.finished_at is not None


@pytest.mark.parametrize(
    "status",
    [AgentRunStatus.FAILED, AgentRunStatus.CANCELLED],
)
def test_finished_at_is_set_for_failed_and_cancelled_statuses(
    tmp_path: Path,
    status: AgentRunStatus,
) -> None:
    """При failed/cancelled устанавливается finished_at."""
    _, session_factory = make_storage(tmp_path)
    repo = AgentRunRepository(session_factory)
    repo.create_run(make_agent_spec(), make_state())

    repo.update_status("run-1", status)

    with session_factory() as session:
        entity = session.get(AgentRunEntity, "run-1")
        assert entity is not None
        assert entity.status == status.value
        assert entity.finished_at is not None


def test_tool_call_log_repository_add_tool_call_stores_call(
    tmp_path: Path,
) -> None:
    """ToolCallLogRepository.add_tool_call сохраняет вызов инструмента."""
    _, session_factory = make_storage(tmp_path)
    repo = ToolCallLogRepository(session_factory)

    repo.add_tool_call(
        run_id="run-1",
        tool_name="fake.read",
        input_data={"запрос": "письма"},
        output_data={"значение": "результат"},
        ok=True,
    )

    calls = repo.list_tool_calls("run-1")
    assert len(calls) == 1


def test_tool_call_log_repository_list_tool_calls_returns_calls(
    tmp_path: Path,
) -> None:
    """ToolCallLogRepository.list_tool_calls возвращает вызовы."""
    _, session_factory = make_storage(tmp_path)
    repo = ToolCallLogRepository(session_factory)
    repo.add_tool_call("run-1", "fake.read", {"q": "тест"}, {"ok": "да"}, True)

    calls = repo.list_tool_calls("run-1")

    assert calls[0]["tool_name"] == "fake.read"
    assert calls[0]["input_data"] == {"q": "тест"}
    assert calls[0]["output_data"] == {"ok": "да"}


def test_audit_log_repository_add_log_stores_event(tmp_path: Path) -> None:
    """AuditLogRepository.add_log сохраняет событие."""
    _, session_factory = make_storage(tmp_path)
    repo = AuditLogRepository(session_factory)

    repo.add_log("agent.created", {"имя": "Агент"}, run_id=None)

    logs = repo.list_logs()
    assert len(logs) == 1


def test_audit_log_repository_list_logs_returns_event(tmp_path: Path) -> None:
    """AuditLogRepository.list_logs возвращает событие."""
    _, session_factory = make_storage(tmp_path)
    repo = AuditLogRepository(session_factory)
    repo.add_log("run.created", {"статус": "создан"}, run_id="run-1")

    logs = repo.list_logs("run-1")

    assert logs[0]["action"] == "run.created"
    assert logs[0]["details"] == {"статус": "создан"}


def test_json_preserves_russian_text(tmp_path: Path) -> None:
    """Все JSON сохраняются с русским текстом без потери символов."""
    _, session_factory = make_storage(tmp_path)
    agent_repo = AgentRepository(session_factory)
    tool_log_repo = ToolCallLogRepository(session_factory)
    audit_log_repo = AuditLogRepository(session_factory)

    agent_repo.save_agent(make_agent_spec(description="Описание с кириллицей"))
    tool_log_repo.add_tool_call(
        run_id="run-1",
        tool_name="fake.read",
        input_data={"запрос": "письма"},
        output_data={"результат": "найдено"},
        ok=True,
    )
    audit_log_repo.add_log("agent.created", {"событие": "создан агент"})

    with session_factory() as session:
        agent_entity = session.get(AgentEntity, "agent-1")
        tool_log_entity = session.scalars(select(ToolCallLogEntity)).one()
        audit_log_entity = session.scalars(select(AuditLogEntity)).one()
        assert agent_entity is not None
        assert tool_log_entity.output_json is not None
        assert "Описание с кириллицей" in agent_entity.agent_spec_json
        assert "письма" in tool_log_entity.input_json
        assert "найдено" in tool_log_entity.output_json
        assert "создан агент" in audit_log_entity.details_json


def test_storage_tests_do_not_create_default_database(tmp_path: Path) -> None:
    """Тесты используют tmp_path и не создают ./data/agents.db."""
    default_db_path = Path("./data/agents.db")
    existed_before = default_db_path.exists()

    make_storage(tmp_path)

    assert default_db_path.exists() is existed_before
