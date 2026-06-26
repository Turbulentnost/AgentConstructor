"""Тесты анализа требований к данным для Agent Builder."""

import pytest

from agent_desktop_constructor.builder.data_requirements import DataRequirementAnalyzer
from agent_desktop_constructor.builder.graph_templates import AgentTemplateName


def get_requirement_map(requirements):
    """Вернуть требования к данным по имени."""
    return {requirement.name: requirement for requirement in requirements}


def test_task_control_agent_returns_requirements() -> None:
    """Для task_control_agent возвращаются requirements."""
    analyzer = DataRequirementAnalyzer()

    requirements = analyzer.analyze(
        "сформируй отчёт по поручениям",
        AgentTemplateName.TASK_CONTROL_AGENT.value,
    )

    assert requirements


def test_task_control_analysis_period_has_default_value() -> None:
    """analysis_period имеет default_value 'последние 7 дней'."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze("найди поручения", AgentTemplateName.TASK_CONTROL_AGENT.value)
    )

    assert requirements["analysis_period"].default_value == "последние 7 дней"


def test_task_control_mail_source_can_be_found_by_agent() -> None:
    """mail_source can_agent_find=True."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze("найди поручения", AgentTemplateName.TASK_CONTROL_AGENT.value)
    )

    assert requirements["mail_source"].can_agent_find is True


def test_report_recipient_not_requested_when_only_build_report() -> None:
    """report_recipient ask_human_if_missing=False для запроса только на отчёт."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "сформируй отчёт по поручениям",
            AgentTemplateName.TASK_CONTROL_AGENT.value,
        )
    )

    assert requirements["report_recipient"].ask_human_if_missing is False


def test_report_recipient_requested_when_user_wants_send_report() -> None:
    """report_recipient ask_human_if_missing=True при намерении отправки."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "отправь отчёт по поручениям руководителю",
            AgentTemplateName.TASK_CONTROL_AGENT.value,
        )
    )

    assert requirements["report_recipient"].ask_human_if_missing is True


def test_include_attachments_default_is_false() -> None:
    """include_attachments по умолчанию false."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze("найди поручения", AgentTemplateName.TASK_CONTROL_AGENT.value)
    )

    assert requirements["include_attachments"].default_value == "false"


def test_meeting_agent_returns_calendar_source() -> None:
    """Для meeting_agent возвращается calendar_source."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "подготовь протокол совещания",
            AgentTemplateName.MEETING_AGENT.value,
        )
    )

    assert requirements["calendar_source"].source_type == "outlook_calendar"


def test_document_analysis_document_source_asks_human_if_missing() -> None:
    """Для document_analysis_agent document_source ask_human_if_missing=True."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "проанализируй нормативный документ",
            AgentTemplateName.DOCUMENT_ANALYSIS_AGENT.value,
        )
    )

    assert requirements["document_source"].ask_human_if_missing is True


def test_generic_agent_returns_user_goal() -> None:
    """Для generic_agent возвращается user_goal."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "помоги структурировать информацию",
            AgentTemplateName.GENERIC_AGENT.value,
        )
    )

    assert "user_goal" in requirements
    assert requirements["user_goal"].default_value == "помоги структурировать информацию"


def test_empty_user_request_raises_value_error() -> None:
    """Пустой user_request вызывает ValueError."""
    analyzer = DataRequirementAnalyzer()

    with pytest.raises(ValueError, match="user_request"):
        analyzer.analyze("   ", AgentTemplateName.GENERIC_AGENT.value)


def test_empty_template_name_raises_value_error() -> None:
    """Пустой template_name вызывает ValueError."""
    analyzer = DataRequirementAnalyzer()

    with pytest.raises(ValueError, match="template_name"):
        analyzer.analyze("сделай отчёт", "   ")


def test_unknown_template_name_returns_generic_requirements() -> None:
    """Неизвестный template_name возвращает generic requirements."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze("сделай что-нибудь", "unknown_template")
    )

    assert set(requirements) == {"user_goal", "output_format"}


def test_analysis_is_case_insensitive() -> None:
    """Анализ работает без учёта регистра."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "ОТПРАВЬ ОТЧЁТ РУКОВОДИТЕЛЮ",
            AgentTemplateName.TASK_CONTROL_AGENT.value,
        )
    )

    assert requirements["report_recipient"].ask_human_if_missing is True


def test_uppercase_send_report_to_manager_detects_send_intent() -> None:
    """Запрос 'ОТПРАВЬ ОТЧЁТ РУКОВОДИТЕЛЮ' определяет send intent."""
    analyzer = DataRequirementAnalyzer()
    requirements = get_requirement_map(
        analyzer.analyze(
            "ОТПРАВЬ ОТЧЁТ РУКОВОДИТЕЛЮ",
            AgentTemplateName.TASK_CONTROL_AGENT.value,
        )
    )

    assert requirements["report_recipient"].ask_human_if_missing is True
