"""Тесты базовой спецификации агента."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentDataRequirement,
    AgentGoal,
    AgentGraphNode,
    AgentGraphNodeType,
    AgentRuntimeLimits,
    AgentSpec,
    AgentToolPermission,
)


def make_goal() -> AgentGoal:
    """Создать валидную цель агента для тестов."""
    return AgentGoal(
        main_goal="Найти поручения в Outlook и сформировать отчет",
        success_criteria=[
            "Найдены письма-кандидаты с поручениями",
            "Сформирован отчет",
        ],
        forbidden_actions=[
            "Не отправлять письма без подтверждения",
            "Не удалять письма",
        ],
    )


def make_data_requirements() -> list[AgentDataRequirement]:
    """Создать тестовый набор требований к данным."""
    return [
        AgentDataRequirement(
            name="mail_source",
            description="Источник писем",
            source_type="outlook",
            required=True,
            can_agent_find=True,
            default_value="Outlook Inbox",
            ask_human_if_missing=False,
        ),
        AgentDataRequirement(
            name="report_recipient",
            description="Получатель отчета",
            source_type="user",
            required=False,
            can_agent_find=False,
            default_value=None,
            ask_human_if_missing=True,
        ),
    ]


def make_tools() -> list[AgentToolPermission]:
    """Создать валидный список разрешений инструментов."""
    return [
        AgentToolPermission(
            tool_name="outlook.search_mail",
            action_level=AgentActionLevel.READ,
            requires_human_approval=False,
            allowed=True,
        ),
        AgentToolPermission(
            tool_name="report.build_task_report",
            action_level=AgentActionLevel.CREATE_DRAFT,
            requires_human_approval=False,
            allowed=True,
        ),
        AgentToolPermission(
            tool_name="email.send",
            action_level=AgentActionLevel.DANGEROUS,
            requires_human_approval=True,
            allowed=False,
        ),
    ]


def make_graph_nodes() -> list[AgentGraphNode]:
    """Создать валидный граф агента для тестов."""
    return [
        AgentGraphNode(
            node_id="validate_request",
            node_type=AgentGraphNodeType.VALIDATION,
            title="Проверить запрос",
            description="Проверить входные данные",
            tool_name=None,
            next_on_success="read_mail",
            next_on_error=None,
            requires_human_approval=False,
        ),
        AgentGraphNode(
            node_id="read_mail",
            node_type=AgentGraphNodeType.TOOL_CALL,
            title="Прочитать письма Outlook",
            description="Найти письма-кандидаты",
            tool_name="outlook.search_mail",
            next_on_success="build_report",
            next_on_error=None,
            requires_human_approval=False,
        ),
        AgentGraphNode(
            node_id="build_report",
            node_type=AgentGraphNodeType.TOOL_CALL,
            title="Сформировать отчет",
            description="Создать черновик отчета",
            tool_name="report.build_task_report",
            next_on_success="final",
            next_on_error=None,
            requires_human_approval=False,
        ),
        AgentGraphNode(
            node_id="final",
            node_type=AgentGraphNodeType.FINAL,
            title="Завершить работу",
            description="Завершить выполнение агента",
            tool_name=None,
            next_on_success=None,
            next_on_error=None,
            requires_human_approval=False,
        ),
    ]


def make_agent_spec(
    *,
    graph_nodes: list[AgentGraphNode] | None = None,
    tools: list[AgentToolPermission] | None = None,
) -> AgentSpec:
    """Создать валидную спецификацию агента с возможностью переопределений."""
    return AgentSpec(
        agent_id="task_report_agent",
        name="Агент контроля поручений",
        description="Ищет поручения и формирует отчет",
        goal=make_goal(),
        data_requirements=make_data_requirements(),
        tools=tools if tools is not None else make_tools(),
        graph_nodes=graph_nodes if graph_nodes is not None else make_graph_nodes(),
        runtime_limits=AgentRuntimeLimits(),
    )


def test_valid_agent_spec_can_be_created() -> None:
    """Валидная спецификация агента создается."""
    spec = make_agent_spec()

    assert spec.agent_id == "task_report_agent"


def test_empty_graph_nodes_raises_error() -> None:
    """Пустой список graph_nodes вызывает ошибку валидации."""
    with pytest.raises(ValidationError):
        make_agent_spec(graph_nodes=[])


def test_duplicate_node_id_raises_error() -> None:
    """Дублирующийся node_id вызывает ошибку валидации."""
    nodes = make_graph_nodes()
    nodes[1] = nodes[1].model_copy(update={"node_id": "validate_request"})

    with pytest.raises(ValidationError, match="node_id"):
        make_agent_spec(graph_nodes=nodes)


def test_tool_call_with_unknown_tool_raises_error() -> None:
    """tool_call на неизвестный инструмент вызывает ошибку."""
    nodes = make_graph_nodes()
    nodes[1] = nodes[1].model_copy(update={"tool_name": "unknown.tool"})

    with pytest.raises(ValidationError, match="unknown.tool"):
        make_agent_spec(graph_nodes=nodes)


def test_dangerous_tool_without_approval_raises_error() -> None:
    """dangerous-инструмент без HumanApproval вызывает ошибку."""
    with pytest.raises(ValidationError, match="dangerous"):
        AgentToolPermission(
            tool_name="email.send",
            action_level=AgentActionLevel.DANGEROUS,
            requires_human_approval=False,
            allowed=True,
        )


def test_next_on_success_with_unknown_node_id_raises_error() -> None:
    """Переход next_on_success на неизвестный узел вызывает ошибку."""
    nodes = make_graph_nodes()
    nodes[0] = nodes[0].model_copy(update={"next_on_success": "missing_node"})

    with pytest.raises(ValidationError, match="missing_node"):
        make_agent_spec(graph_nodes=nodes)


def test_get_start_node_returns_first_node() -> None:
    """get_start_node возвращает первый узел графа."""
    spec = make_agent_spec()

    assert spec.get_start_node().node_id == "validate_request"


def test_get_node_returns_requested_node() -> None:
    """get_node возвращает узел по node_id."""
    spec = make_agent_spec()

    assert spec.get_node("read_mail").title == "Прочитать письма Outlook"


def test_get_node_raises_value_error_for_unknown_node_id() -> None:
    """get_node выбрасывает ValueError для неизвестного node_id."""
    spec = make_agent_spec()

    with pytest.raises(ValueError, match="not_found"):
        spec.get_node("not_found")


def test_required_human_inputs_returns_only_human_requirements() -> None:
    """required_human_inputs возвращает только ручные требования к данным."""
    spec = make_agent_spec()

    requirements = spec.required_human_inputs()

    assert [requirement.name for requirement in requirements] == ["report_recipient"]


def test_allowed_tool_names_returns_only_allowed_tools() -> None:
    """allowed_tool_names возвращает только разрешенные инструменты."""
    spec = make_agent_spec()

    assert spec.allowed_tool_names() == {
        "outlook.search_mail",
        "report.build_task_report",
    }


def test_tool_call_node_without_tool_name_raises_error() -> None:
    """tool_call-узел без tool_name вызывает ошибку."""
    with pytest.raises(ValidationError, match="tool_name"):
        AgentGraphNode(
            node_id="read_mail",
            node_type=AgentGraphNodeType.TOOL_CALL,
            title="Прочитать письма Outlook",
            description="Найти письма-кандидаты",
            tool_name=None,
            next_on_success="final",
            next_on_error=None,
            requires_human_approval=False,
        )


def test_agent_spec_without_final_node_raises_error() -> None:
    """Спецификация без final-узла вызывает ошибку."""
    nodes = [
        node for node in make_graph_nodes()
        if node.node_type != AgentGraphNodeType.FINAL
    ]
    nodes[-1] = nodes[-1].model_copy(update={"next_on_success": None})

    with pytest.raises(ValidationError, match="final"):
        make_agent_spec(graph_nodes=nodes)
