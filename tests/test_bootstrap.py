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
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry


def test_build_application_container_creates_container() -> None:
    """build_application_container создаёт ApplicationContainer."""
    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert isinstance(container, ApplicationContainer)


def test_container_contains_agent_builder() -> None:
    """Container содержит AgentBuilder."""
    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert isinstance(container.agent_builder, AgentBuilder)


def test_container_contains_tool_registry() -> None:
    """Container содержит ToolRegistry."""
    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert isinstance(container.tool_registry, ToolRegistry)


def test_container_contains_tool_gateway() -> None:
    """Container содержит ToolGateway."""
    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert isinstance(container.tool_gateway, ToolGateway)


def test_container_contains_runtime() -> None:
    """Container содержит SimpleAgentRuntime."""
    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert isinstance(container.runtime, SimpleAgentRuntime)


def test_container_contains_agent_service() -> None:
    """Container содержит AgentApplicationService."""
    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert isinstance(container.agent_service, AgentApplicationService)


def test_bootstrap_does_not_call_tools(monkeypatch) -> None:
    """Bootstrap не вызывает инструменты."""
    from agent_desktop_constructor.tools.fake_task_control_tools import (
        FakeOutlookSearchMailTool,
    )

    def fail_execute(self, input_data):
        raise AssertionError("bootstrap не должен вызывать execute")

    monkeypatch.setattr(FakeOutlookSearchMailTool, "execute", fail_execute)

    container = build_application_container(AppConfig(run_mode=AppRunMode.FAKE))

    assert container.tool_registry.has_tool("outlook.search_mail")


def test_bootstrap_outlook_readonly_does_not_require_com() -> None:
    """Bootstrap outlook_readonly собирается без прямого COM-вызова."""
    container = build_application_container(
        AppConfig(run_mode=AppRunMode.OUTLOOK_READONLY)
    )

    assert container.tool_registry.has_tool("outlook.search_mail")


def test_bootstrap_outlook_readonly_does_not_execute_worker(monkeypatch) -> None:
    """Bootstrap outlook_readonly не вызывает SubprocessComWorker.execute."""
    from agent_desktop_constructor.workers.subprocess_com_worker import (
        SubprocessComWorker,
    )

    def fail_execute(self, task):
        raise AssertionError("bootstrap не должен вызывать COM worker execute")

    monkeypatch.setattr(SubprocessComWorker, "execute", fail_execute)

    container = build_application_container(
        AppConfig(run_mode=AppRunMode.OUTLOOK_READONLY)
    )

    assert container.tool_registry.has_tool("outlook.read_calendar")


def test_bootstrap_with_llm_disabled_does_not_call_http(monkeypatch) -> None:
    """use_llm_planner=False не делает HTTP-запросов при bootstrap."""
    from agent_desktop_constructor.app.llm import client as llm_client_module

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("bootstrap не должен делать HTTP-запрос")

    monkeypatch.setattr(llm_client_module.request, "urlopen", fail_urlopen)

    container = build_application_container(
        AppConfig(run_mode=AppRunMode.FAKE, use_llm_planner=False)
    )

    assert isinstance(container.agent_builder, AgentBuilder)

