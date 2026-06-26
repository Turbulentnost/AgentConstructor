"""Тесты эвристического выбора шаблона агента."""

import pytest

from agent_desktop_constructor.builder.graph_templates import AgentTemplateName
from agent_desktop_constructor.builder.template_selector import TemplateSelector


def test_outlook_tasks_request_selects_task_control_agent() -> None:
    """Запрос про поручения в Outlook выбирает task_control_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("найди поручения в Outlook")
        == AgentTemplateName.TASK_CONTROL_AGENT.value
    )


def test_overdue_tasks_request_selects_task_control_agent() -> None:
    """Запрос про контроль просроченных задач выбирает task_control_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("контроль просроченных задач")
        == AgentTemplateName.TASK_CONTROL_AGENT.value
    )


def test_meeting_minutes_request_selects_meeting_agent() -> None:
    """Запрос про протокол совещания выбирает meeting_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("сделай протокол совещания")
        == AgentTemplateName.MEETING_AGENT.value
    )


def test_meeting_agenda_request_selects_meeting_agent() -> None:
    """Запрос про повестку встречи выбирает meeting_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("подготовь повестку встречи")
        == AgentTemplateName.MEETING_AGENT.value
    )


def test_document_request_selects_document_analysis_agent() -> None:
    """Запрос про нормативный документ выбирает document_analysis_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("проанализируй нормативный документ")
        == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value
    )


def test_nd_impact_analysis_request_selects_document_analysis_agent() -> None:
    """Запрос про анализ влияния изменения НД выбирает document_analysis_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("анализ влияния изменения НД")
        == AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value
    )


def test_neutral_request_selects_generic_agent() -> None:
    """Нейтральный запрос выбирает generic_agent."""
    selector = TemplateSelector()

    assert (
        selector.select_template("помоги структурировать информацию")
        == AgentTemplateName.GENERIC_AGENT.value
    )


def test_empty_request_raises_value_error() -> None:
    """Пустой запрос вызывает ValueError."""
    selector = TemplateSelector()

    with pytest.raises(ValueError, match="user_request"):
        selector.select_template("   ")


def test_case_does_not_affect_result() -> None:
    """Регистр не влияет на выбор шаблона."""
    selector = TemplateSelector()

    assert (
        selector.select_template("СДЕЛАЙ ПРОТОКОЛ СОВЕЩАНИЯ")
        == AgentTemplateName.MEETING_AGENT.value
    )
