"""Тесты ApplicationContainer bootstrap."""

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.bootstrap import (
    ApplicationContainer,
    build_application_container,
)
from agent_desktop_constructor.app.core.config import AppConfig
from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.storage.repositories import (
    AgentRepository,
    AgentRunRepository,
    AuditLogRepository,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def config_for_tmp_db(tmp_path, run_mode: AppRunMode = AppRunMode.FAKE) -> AppConfig:
    """Создать AppConfig с временной SQLite базой."""
    return AppConfig(run_mode=run_mode, database_path=str(tmp_path / "agents.db"))


def test_build_application_container_creates_container(tmp_path) -> None:
    """build_application_container создаёт ApplicationContainer."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container, ApplicationContainer)


def test_container_contains_agent_builder(tmp_path) -> None:
    """Container содержит AgentBuilder."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container.agent_builder, AgentBuilder)


def test_container_contains_tool_registry(tmp_path) -> None:
    """Container содержит ToolRegistry."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container.tool_registry, ToolRegistry)


def test_container_contains_tool_gateway(tmp_path) -> None:
    """Container содержит ToolGateway."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container.tool_gateway, ToolGateway)


def test_container_contains_runtime(tmp_path) -> None:
    """Container содержит SimpleAgentRuntime."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container.runtime, SimpleAgentRuntime)


def test_container_contains_agent_service(tmp_path) -> None:
    """Container содержит AgentApplicationService."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container.agent_service, AgentApplicationService)


def test_container_contains_repositories(tmp_path) -> None:
    """Container содержит storage repositories."""
    container = build_application_container(config_for_tmp_db(tmp_path))

    assert isinstance(container.agent_repository, AgentRepository)
    assert isinstance(container.run_repository, AgentRunRepository)
    assert isinstance(container.audit_repository, AuditLogRepository)
    assert container.session_factory is not None


def test_bootstrap_does_not_call_tools(monkeypatch, tmp_path) -> None:
    """Bootstrap не вызывает инструменты."""
    from agent_desktop_constructor.tools.fake_task_control_tools import (
        FakeOutlookSearchMailTool,
    )

    def fail_execute(self, input_data):
        raise AssertionError("bootstrap не должен вызывать execute")

    monkeypatch.setattr(FakeOutlookSearchMailTool, "execute", fail_execute)

    container = build_application_container(config_for_tmp_db(tmp_path))

    assert container.tool_registry.has_tool("outlook.search_mail")


def test_bootstrap_outlook_readonly_does_not_require_com(tmp_path) -> None:
    """Bootstrap outlook_readonly собирается без прямого COM-вызова."""
    container = build_application_container(
        config_for_tmp_db(tmp_path, AppRunMode.OUTLOOK_READONLY)
    )

    assert container.tool_registry.has_tool("outlook.search_mail")


def test_bootstrap_outlook_readonly_does_not_execute_worker(monkeypatch, tmp_path) -> None:
    """Bootstrap outlook_readonly не вызывает SubprocessComWorker.execute."""
    from agent_desktop_constructor.workers.subprocess_com_worker import (
        SubprocessComWorker,
    )

    def fail_execute(self, task):
        raise AssertionError("bootstrap не должен вызывать COM worker execute")

    monkeypatch.setattr(SubprocessComWorker, "execute", fail_execute)

    container = build_application_container(
        config_for_tmp_db(tmp_path, AppRunMode.OUTLOOK_READONLY)
    )

    assert container.tool_registry.has_tool("outlook.read_calendar")


def test_bootstrap_with_llm_disabled_does_not_call_http(monkeypatch, tmp_path) -> None:
    """use_llm_planner=False не делает HTTP-запросов при bootstrap."""
    from agent_desktop_constructor.app.llm import client as llm_client_module

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("bootstrap не должен делать HTTP-запрос")

    monkeypatch.setattr(llm_client_module.request, "urlopen", fail_urlopen)

    container = build_application_container(
        AppConfig(
            run_mode=AppRunMode.FAKE,
            database_path=str(tmp_path / "agents.db"),
            use_llm_planner=False,
        )
    )

    assert isinstance(container.agent_builder, AgentBuilder)

