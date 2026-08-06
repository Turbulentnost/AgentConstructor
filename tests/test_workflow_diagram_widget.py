"""Тесты вертикальной блок-схемы workflow."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.app.ui.widgets.workflow_diagram_widget import (
    WorkflowDiagramWidget,
)
from agent_desktop_constructor.core.models.agent_spec import (
    AgentGraphNode,
    AgentGraphNodeType,
)


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_workflow_diagram_set_graph_orders_nodes(qt_app) -> None:
    """set_graph строит карточки по next_on_success."""
    nodes = [
        AgentGraphNode(
            node_id="a",
            node_type=AgentGraphNodeType.PLANNING,
            title="Старт",
            description="Начало",
            tool_name=None,
            next_on_success="b",
            next_on_error=None,
            requires_human_approval=False,
        ),
        AgentGraphNode(
            node_id="b",
            node_type=AgentGraphNodeType.TOOL_CALL,
            title="Шаг данных",
            description="Сбор",
            tool_name="excel.read_sheet",
            next_on_success="c",
            next_on_error="c",
            requires_human_approval=False,
        ),
        AgentGraphNode(
            node_id="c",
            node_type=AgentGraphNodeType.FINAL,
            title="Финиш",
            description="Итог",
            tool_name=None,
            next_on_success=None,
            next_on_error=None,
            requires_human_approval=False,
        ),
    ]
    widget = WorkflowDiagramWidget()
    widget.set_graph(nodes)
    assert [node.node_id for node in widget.nodes()] == ["a", "b", "c"]
    assert widget._host_layout.count() >= 5  # 3 cards + 2 connectors (+ stretch)


def test_workflow_diagram_empty_shows_placeholder(qt_app) -> None:
    """Пустой граф показывает подсказку."""
    widget = WorkflowDiagramWidget()
    widget.show()
    widget.set_graph([])
    qt_app.processEvents()
    assert not widget._empty.isHidden()
