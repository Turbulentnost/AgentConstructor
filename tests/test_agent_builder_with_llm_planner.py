"""Тесты опционального подключения LLM AgentPlan planner к AgentBuilder."""

import pytest
import inspect

from agent_desktop_constructor.app.llm.agent_plan_models import (
    LLMAgentPlan,
    LLMPlannedStep,
    LLMPlannedTool,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class FakePlanner:
    """Fake LLMPlanner для AgentBuilder-тестов без HTTP."""

    def __init__(
        self,
        result: LLMAgentPlan | None = None,
    ) -> None:
        """Сохранить result и счётчик вызовов."""
        self.result = result or planning_result()
        self.call_count = 0
        self.last_user_request: str | None = None
        self.last_catalog = None

    def plan(
        self,
        user_request: str,
        tools_catalog,
    ) -> LLMAgentPlan:
        """Вернуть fake planning result."""
        self.call_count += 1
        self.last_user_request = user_request
        self.last_catalog = tools_catalog
        return self.result


def planning_result(
    tool_name: str = "outlook.search_mail",
    *,
    needs_human: bool = False,
) -> LLMAgentPlan:
    """Создать валидный LLMAgentPlan."""
    return LLMAgentPlan(
        agent_name="LLM агент",
        goal="Найти поручения в Outlook",
        selected_tools=[
            LLMPlannedTool(
                tool_name=tool_name,
                reason="Нужно прочитать данные",
            )
        ],
        steps=[
            LLMPlannedStep(
                step_id="read_data",
                step_type="tool_call",
                title="Прочитать данные",
                description="Вызвать выбранный LLM tool",
                tool_name=tool_name,
            )
        ],
        missing_data=[],
        needs_human=needs_human,
        warnings=[],
    )


def test_agent_builder_without_llm_does_not_call_planner() -> None:
    """use_llm_planner=False не вызывает LLMPlanner."""
    planner = FakePlanner()
    builder = AgentBuilder(llm_planner=planner, use_llm_planner=False)

    builder.build_from_request("создай агента контроля поручений")

    assert planner.call_count == 0


def test_agent_builder_with_llm_calls_planner() -> None:
    """use_llm_planner=True вызывает LLM planner с ToolsCatalog."""
    planner = FakePlanner()
    builder = AgentBuilder(llm_planner=planner, use_llm_planner=True)

    builder.build_from_request("создай агента контроля поручений")

    assert planner.call_count == 1
    assert planner.last_catalog is not None


def test_agent_builder_with_llm_rejects_unknown_tool() -> None:
    """AgentBuilder с LLM повторно не принимает unknown tool."""
    planner = FakePlanner(planning_result("invented.tool"))
    builder = AgentBuilder(llm_planner=planner, use_llm_planner=True)

    with pytest.raises(ValueError, match="invented.tool"):
        builder.build_from_request("создай агента контроля поручений")


def test_agent_builder_with_llm_still_validates_agent_spec_tools() -> None:
    """AgentBuilder с LLM всё равно строит AgentSpec и валидирует его по ToolsCatalog."""
    catalog = load_tools_catalog()
    builder = AgentBuilder(
        tools_catalog=catalog,
        llm_planner=FakePlanner(),
        use_llm_planner=True,
    )

    agent_spec = builder.build_from_request("создай агента контроля поручений")

    assert isinstance(agent_spec, AgentSpec)
    catalog.validate_tool_names([tool.tool_name for tool in agent_spec.tools])


def test_agent_builder_with_llm_uses_plan_graph() -> None:
    """LLM-план заменяет template graph в LLM режиме."""
    builder = AgentBuilder(llm_planner=FakePlanner(), use_llm_planner=True)

    agent_spec = builder.build_from_request("создай агента контроля поручений")

    actual_node_ids = [node.node_id for node in agent_spec.graph_nodes]
    assert actual_node_ids[:2] == ["read_data", "final"]


def test_agent_builder_with_llm_does_not_use_tool_gateway() -> None:
    """Builder не исполняет инструменты и не использует ToolGateway при сборке."""
    source = inspect.getsource(AgentBuilder)

    assert "ToolGateway" not in source
    assert "execute_tool" not in source


def test_agent_builder_with_llm_adds_requirement_when_new_tool_needed() -> None:
    """needs_human=True добавляет требование для человека."""
    planner = FakePlanner(planning_result(needs_human=True))
    builder = AgentBuilder(llm_planner=planner, use_llm_planner=True)

    agent_spec = builder.build_from_request("создай агента контроля поручений")

    requirements = {
        requirement.name: requirement for requirement in agent_spec.data_requirements
    }
    requirement = requirements["new_tool_or_human_needed"]
    assert requirement.ask_human_if_missing is True
    assert requirement.required is True


def test_agent_builder_requires_planner_when_llm_enabled() -> None:
    """use_llm_planner=True без llm_planner даёт понятную ошибку."""
    builder = AgentBuilder(use_llm_planner=True)

    with pytest.raises(ValueError, match="llm_planner"):
        builder.build_from_request("создай агента контроля поручений")

