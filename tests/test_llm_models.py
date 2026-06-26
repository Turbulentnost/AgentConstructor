"""Тесты моделей безопасного LLM planner-а."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.models import (
    LLMPlanningResult,
    ToolSelectionItem,
    parse_planning_result,
)


def test_llm_planning_result_can_be_created() -> None:
    """LLMPlanningResult создаётся с выбранными инструментами."""
    result = LLMPlanningResult(
        understood_goal="Найти поручения в Outlook",
        selected_tools=[
            ToolSelectionItem(
                tool_name="outlook.search_mail",
                reason="Нужно прочитать письма",
                required=True,
            )
        ],
        missing_data=[],
        needs_human=False,
        needs_human_reason=None,
    )

    assert result.understood_goal == "Найти поручения в Outlook"
    assert result.selected_tools[0].tool_name == "outlook.search_mail"


def test_needs_human_true_can_include_reason() -> None:
    """needs_human=True валиден с заполненной причиной."""
    result = LLMPlanningResult(
        understood_goal="Отправить отчёт",
        selected_tools=[],
        missing_data=["получатель"],
        needs_human=True,
        needs_human_reason="Нужен получатель и подтверждение отправки",
    )

    assert result.needs_human is True


def test_empty_tool_name_raises_error() -> None:
    """Пустой tool_name вызывает ошибку валидации."""
    with pytest.raises(ValidationError):
        ToolSelectionItem(tool_name="", reason="Нужно прочитать почту", required=True)


def test_parse_planning_result_parses_valid_json() -> None:
    """parse_planning_result парсит валидный JSON."""
    result = parse_planning_result(
        """
        {
          "understood_goal": "Найти поручения",
          "selected_tools": [
            {
              "tool_name": "outlook.search_mail",
              "reason": "Письма могут содержать поручения",
              "required": true
            }
          ],
          "missing_data": [],
          "needs_human": false,
          "needs_human_reason": null,
          "needs_human_or_new_tool": false,
          "warnings": []
        }
        """
    )

    assert result.understood_goal == "Найти поручения"
    assert result.selected_tools[0].required is True


def test_parse_planning_result_raises_on_invalid_json() -> None:
    """parse_planning_result падает на невалидном JSON."""
    with pytest.raises(LLMInvalidJSONError):
        parse_planning_result("{not-json")


def test_parse_planning_result_raises_on_schema_validation_error() -> None:
    """parse_planning_result падает, если JSON не проходит Pydantic-схему."""
    with pytest.raises(LLMInvalidJSONError):
        parse_planning_result(
            """
            {
              "understood_goal": "",
              "selected_tools": [],
              "missing_data": [],
              "needs_human": true,
              "needs_human_reason": null
            }
            """
        )

