"""Вертикальная блок-схема workflow по AgentGraphNode."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from agent_desktop_constructor.core.models.agent_spec import (
    AgentGraphNode,
    AgentGraphNodeType,
)

_CARD = "#161625"
_TEXT = "#e8eaf2"
_MUTED = "#8a8fa3"
_LINE = "#2a2a3d"
_ACCENT = "#5856D6"
_BLUE = "#3b82f6"

_TYPE_ICON = {
    AgentGraphNodeType.VALIDATION: ("✓", _BLUE),
    AgentGraphNodeType.PLANNING: ("⚡", _ACCENT),
    AgentGraphNodeType.DATA_SEARCH: ("🗄", _BLUE),
    AgentGraphNodeType.TOOL_CALL: ("⚙", _ACCENT),
    AgentGraphNodeType.ANALYSIS: ("🔎", _BLUE),
    AgentGraphNodeType.ROUTING: ("⤵", _ACCENT),
    AgentGraphNodeType.HUMAN_REVIEW: ("👤", _ACCENT),
    AgentGraphNodeType.FINAL: ("✔", _BLUE),
}


class WorkflowDiagramWidget(QWidget):
    """Read-only вертикальная диаграмма узлов графа агента."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowDiagram")
        self._nodes: list[AgentGraphNode] = []

        self._title = QLabel("Workflow агента")
        self._title.setObjectName("wfTitle")

        self._empty = QLabel(
            "Диаграмма появится после успешного пробного запуска."
        )
        self._empty.setObjectName("wfEmpty")
        self._empty.setWordWrap(True)

        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(8, 8, 8, 8)
        self._host_layout.setSpacing(0)
        self._host_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._host)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._title)
        root.addWidget(self._empty)
        root.addWidget(scroll, 1)

        self.setStyleSheet(
            "#workflowDiagram { background: #0B0B14; }"
            f"#wfTitle {{ color: {_TEXT}; font-size: 16px; font-weight: 800; }}"
            f"#wfEmpty {{ color: {_MUTED}; font-size: 12px; }}"
            f"#wfNode {{ background: {_CARD}; border: 1px solid {_LINE};"
            "border-radius: 12px; }}"
            f"#wfNodeTitle {{ color: {_TEXT}; font-size: 13px; font-weight: 700; }}"
            f"#wfNodeDesc {{ color: {_MUTED}; font-size: 11px; }}"
            f"#wfConnector {{ background: {_LINE}; }}"
            "#wfPlay { color: #6b7088; font-size: 14px; }"
        )

    def nodes(self) -> list[AgentGraphNode]:
        """Текущие узлы диаграммы."""
        return list(self._nodes)

    def set_graph(self, nodes: list[AgentGraphNode] | None) -> None:
        """Отрисовать узлы сверху вниз с соединительными линиями."""
        self._nodes = list(nodes or [])
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._nodes:
            self._empty.setVisible(True)
            return

        self._empty.setVisible(False)
        by_id = {node.node_id: node for node in self._nodes}
        ordered = self._order_nodes(self._nodes, by_id)
        for index, node in enumerate(ordered):
            self._host_layout.addWidget(self._build_node_card(node))
            if index < len(ordered) - 1:
                self._host_layout.addWidget(self._build_connector(), 0, Qt.AlignmentFlag.AlignHCenter)
        self._host_layout.addStretch(1)

    def _build_node_card(self, node: AgentGraphNode) -> QFrame:
        card = QFrame()
        card.setObjectName("wfNode")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)

        icon_text, color = _TYPE_ICON.get(node.node_type, ("●", _ACCENT))
        icon = QLabel(icon_text)
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background:{color}; color:white; border-radius:10px; font-size:14px;"
        )

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(node.title or node.node_id)
        title.setObjectName("wfNodeTitle")
        title.setWordWrap(True)
        desc = QLabel(node.description or (node.tool_name or node.node_type.value))
        desc.setObjectName("wfNodeDesc")
        desc.setWordWrap(True)
        text_col.addWidget(title)
        text_col.addWidget(desc)

        play = QLabel("▶")
        play.setObjectName("wfPlay")

        row.addWidget(icon)
        row.addLayout(text_col, 1)
        row.addWidget(play)
        return card

    def _build_connector(self) -> QWidget:
        line = QFrame()
        line.setObjectName("wfConnector")
        line.setFixedWidth(2)
        line.setFixedHeight(18)
        return line

    @staticmethod
    def _order_nodes(
        nodes: list[AgentGraphNode],
        by_id: dict[str, AgentGraphNode],
    ) -> list[AgentGraphNode]:
        """Пройти граф по next_on_success, иначе сохранить исходный порядок."""
        if not nodes:
            return []
        start = nodes[0]
        ordered: list[AgentGraphNode] = []
        seen: set[str] = set()
        current: AgentGraphNode | None = start
        while current is not None and current.node_id not in seen:
            ordered.append(current)
            seen.add(current.node_id)
            nxt = current.next_on_success
            current = by_id.get(nxt) if nxt else None
        for node in nodes:
            if node.node_id not in seen:
                ordered.append(node)
        return ordered
