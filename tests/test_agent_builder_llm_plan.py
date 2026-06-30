"""Тесты AgentBuilder, строящего AgentSpec из LLMAgentPlan."""

import inspect

from agent_desktop_constructor.app.llm.agent_plan_models import (
    LLMAgentPlan,
    LLMPlannedStep,
    LLMPlannedTool,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder


class FakeLLMToolPlanner:
    """Fake planner, возвращающий LLMAgentPlan."""

    def __init__(self, plan: LLMAgentPlan) -> None:
        self.plan_result = plan
        self.call_count = 0
        self.last_catalog = None

    def plan(self, user_request: str, tools_catalog):
        """Вернуть заранее заданный план."""
        self.call_count += 1
        self.last_catalog = tools_catalog
        return self.plan_result


def make_plan() -> LLMAgentPlan:
    """Создать LLM-план с одним tool."""
    return LLMAgentPlan(
        agent_name="LLM агент календаря",
        goal="Прочитать календарь и дать вывод",
        selected_tools=[
            LLMPlannedTool(
                tool_name="outlook.read_calendar",
                reason="Нужно прочитать события",
            )
        ],
        steps=[
            LLMPlannedStep(
                step_id="read_calendar",
                step_type="tool_call",
                title="Прочитать календарь",
                description="Получить события Outlook",
                tool_name="outlook.read_calendar",
            ),
            LLMPlannedStep(
                step_id="final_summary",
                step_type="final",
                title="Завершить",
                description="Вернуть результат пользователю",
            ),
        ],
    )


def test_agent_builder_builds_agent_spec_from_llm_agent_plan() -> None:
    """AgentBuilder строит AgentSpec из LLMAgentPlan."""
    planner = FakeLLMToolPlanner(make_plan())
    builder = AgentBuilder(llm_planner=planner, use_llm_planner=True)

    agent_spec = builder.build_from_request("Проверь календарь")

    assert planner.call_count == 1
    assert agent_spec.name == "LLM агент календаря"
    assert agent_spec.goal.main_goal == "Прочитать календарь и дать вывод"
    assert [node.node_id for node in agent_spec.graph_nodes][:2] == [
        "read_calendar",
        "final_summary",
    ]


def test_agent_spec_contains_only_tools_selected_by_llm() -> None:
    """AgentSpec содержит инструменты, выбранные LLM."""
    builder = AgentBuilder(llm_planner=FakeLLMToolPlanner(make_plan()), use_llm_planner=True)

    agent_spec = builder.build_from_request("Проверь календарь")

    assert [tool.tool_name for tool in agent_spec.tools] == ["outlook.read_calendar"]


def test_agent_builder_does_not_add_template_tools_when_llm_enabled() -> None:
    """AgentBuilder не добавляет инструменты вручную, если включён LLM planning."""
    builder = AgentBuilder(llm_planner=FakeLLMToolPlanner(make_plan()), use_llm_planner=True)

    agent_spec = builder.build_from_request(
        "Нужен агент, который смотрит все совещания и планирует график"
    )

    tool_names = {tool.tool_name for tool in agent_spec.tools}
    assert tool_names == {"outlook.read_calendar"}
    assert "llm.analyze_collected_data" not in tool_names
    assert "report.build_schedule_recommendations" not in tool_names


def test_template_fallback_works_only_when_llm_planning_disabled() -> None:
    """Template fallback работает, если LLM planning выключен."""
    planner = FakeLLMToolPlanner(make_plan())
    builder = AgentBuilder(llm_planner=planner, use_llm_planner=False)

    agent_spec = builder.build_from_request(
        "Нужен агент, который смотрит все совещания и планирует график"
    )

    tool_names = {tool.tool_name for tool in agent_spec.tools}
    assert planner.call_count == 0
    assert "report.build_schedule_recommendations" in tool_names


def test_agent_builder_llm_path_does_not_use_tool_gateway_or_execute() -> None:
    """Builder не исполняет tools в LLM-plan режиме."""
    source = inspect.getsource(AgentBuilder)

    assert "ToolGateway" not in source
    assert "execute_tool" not in source
    assert ".execute(" not in source

