"""Тесты устойчивого парсинга решения LLM-цикла."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.app.llm.agent_loop_planner import (
    _extract_first_json_object,
    _parse_agent_loop_decision,
)
from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.supervisor_models import SupervisorDecisionType


def test_parse_plain_json_decision() -> None:
    """Чистый JSON-объект парсится в SupervisorDecision."""
    content = (
        '{"decision_type": "continue_to_next", "reason": "Данные собраны"}'
    )

    decision = _parse_agent_loop_decision(content)

    assert decision.decision_type == SupervisorDecisionType.CONTINUE_TO_NEXT
    assert decision.reason == "Данные собраны"


def test_parse_decision_with_surrounding_prose() -> None:
    """Пояснения до и после JSON не ломают парсинг решения."""
    content = (
        "Вот моё решение:\n"
        '{"decision_type": "finish_success", "reason": "Готово", '
        '"final_message": "Итоговый отчёт по неделям"}\n'
        "Надеюсь, это помогло."
    )

    decision = _parse_agent_loop_decision(content)

    assert decision.decision_type == SupervisorDecisionType.FINISH_SUCCESS
    assert decision.final_message == "Итоговый отчёт по неделям"


def test_extract_first_json_object_ignores_braces_in_strings() -> None:
    """Скобки внутри строковых значений не сбивают границы объекта."""
    text = 'prefix {"reason": "a { b } c", "n": 1} suffix'

    assert _extract_first_json_object(text) == '{"reason": "a { b } c", "n": 1}'


def test_parse_truncated_json_raises_invalid_json() -> None:
    """Обрезанный JSON (незакрытая строка) даёт понятную ошибку."""
    content = '{"decision_type": "finish_success", "final_message": "очень длинный'

    with pytest.raises(LLMInvalidJSONError):
        _parse_agent_loop_decision(content)
