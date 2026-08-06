"""Тесты правой панели «Параметры агента»."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import AppConfig, AppRunMode
from agent_desktop_constructor.app.ui.widgets.agent_card_panel import AgentCardPanel
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


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_container(tmp_path):
    return build_application_container(
        AppConfig(
            run_mode=AppRunMode.FAKE,
            database_path=str(tmp_path / "ui-card-tests.db"),
        )
    )


def _sample_agent() -> AgentSpec:
    return AgentSpec(
        agent_id="agent-card-1",
        name="Контроль документов",
        description="Проверяет документы",
        goal=AgentGoal(
            main_goal="Подготовить расхождения для проверки",
            success_criteria=["Готово"],
            forbidden_actions=[],
        ),
        data_requirements=[
            AgentDataRequirement(
                name="source",
                description="Откуда брать документы?",
                source_type="email",
                required=True,
                can_agent_find=True,
                default_value=None,
                ask_human_if_missing=False,
            )
        ],
        tools=[
            AgentToolPermission(
                tool_name="email.list_messages",
                action_level=AgentActionLevel.READ,
                requires_human_approval=False,
                allowed=True,
            )
        ],
        graph_nodes=[
            AgentGraphNode(
                node_id="step1",
                node_type=AgentGraphNodeType.TOOL_CALL,
                title="Получить документы",
                description="Читает почту",
                tool_name="email.list_messages",
                next_on_success="final",
                next_on_error="final",
                requires_human_approval=False,
            ),
            AgentGraphNode(
                node_id="final",
                node_type=AgentGraphNodeType.FINAL,
                title="Итог",
                description="Готово",
                tool_name=None,
                next_on_success=None,
                next_on_error=None,
                requires_human_approval=False,
            ),
        ],
        runtime_limits=AgentRuntimeLimits(),
    )


def test_agent_card_panel_bind_and_apply(qt_app) -> None:
    """bind заполняет поля, apply_edits_to_spec возвращает правки."""
    panel = AgentCardPanel()
    agent = _sample_agent()
    panel.bind_agent_spec(agent, ["C:/tmp/Шаблон.xlsx"])

    assert panel.name_edit.text() == "Контроль документов"
    assert "Подготовить расхождения" in panel.goal_edit.toPlainText()
    assert panel.next_button.isEnabled()
    assert "источников" in panel.meta_label.text()

    panel.name_edit.setText("Новое имя")
    panel.goal_edit.setPlainText("Новая цель")
    updated = panel.apply_edits_to_spec(agent)
    assert updated.name == "Новое имя"
    assert updated.goal.main_goal == "Новая цель"


def test_wizard_step_gating_blocks_workflow_without_trial(qt_app, fake_container) -> None:
    """На Workflow нельзя перейти без успешного пробного запуска."""
    from agent_desktop_constructor.app.ui.widgets.agent_create_widget import (
        AgentCreateWidget,
    )
    from agent_desktop_constructor.app.ui.widgets.wizard_stepper import WizardStep

    widget = AgentCreateWidget(fake_container)
    widget._preview_agent = _sample_agent()
    widget._trial_passed = False
    widget._goto_wizard_step(WizardStep.WORKFLOW, unlock=False)
    assert widget._wizard_stack.currentIndex() == int(WizardStep.PLANNING)

    widget._trial_passed = True
    widget._goto_wizard_step(WizardStep.WORKFLOW, unlock=True)
    assert widget._wizard_stack.currentIndex() == int(WizardStep.WORKFLOW)
