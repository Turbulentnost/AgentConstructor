"""Тесты устойчивого парсинга решения LLM-цикла."""

from __future__ import annotations

import pytest

from types import SimpleNamespace

from agent_desktop_constructor.app.llm.agent_loop_planner import (
    LLMAgentLoopPlanner,
    _extract_first_json_object,
    _parse_agent_loop_decision,
    _require_thought,
)
from agent_desktop_constructor.app.llm.errors import LLMInvalidJSONError
from agent_desktop_constructor.app.llm.supervisor_models import (
    AgentThought,
    SupervisorDecision,
    SupervisorDecisionType,
)
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog


class _FakeLLMClient:
    """Минимальный LLM-клиент, отдающий заранее заданный JSON решения."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.config = SimpleNamespace(temperature=0.0, model_name="fake")

    def complete(self, request):  # noqa: ANN001 - тестовый двойник
        return SimpleNamespace(content=self._content)


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


def test_tool_name_in_decision_type_is_coerced_to_call_tool() -> None:
    """LLM положила имя инструмента в decision_type — чиним в call_tool."""
    content = (
        '{"decision_type": "browser.screenshot", '
        '"reason": "Нужен свежий кадр", '
        '"input_data": {"selector": "body"}}'
    )

    decision = _parse_agent_loop_decision(content)

    assert decision.decision_type == SupervisorDecisionType.CALL_TOOL
    assert decision.tool_call is not None
    assert decision.tool_call.tool_name == "browser.screenshot"
    assert decision.tool_call.input_data == {"selector": "body"}


def test_top_level_tool_name_is_wrapped_into_tool_call() -> None:
    """call_tool без вложенного tool_call, но с tool_name сверху — оборачиваем."""
    content = (
        '{"decision_type": "call_tool", "reason": "Кликаю кнопку", '
        '"tool_name": "browser.click", "input_data": {"x": 10, "y": 20}}'
    )

    decision = _parse_agent_loop_decision(content)

    assert decision.decision_type == SupervisorDecisionType.CALL_TOOL
    assert decision.tool_call is not None
    assert decision.tool_call.tool_name == "browser.click"
    assert decision.tool_call.input_data == {"x": 10, "y": 20}


def test_parse_thought_block_is_normalized() -> None:
    """Блок THINK парсится в structured thought с полями AgentThought."""
    content = (
        '{"thought": {"understanding": "Нужна погода", '
        '"missing": "нет данных", "plan": ["открыть сайт"], '
        '"tool": "browser.navigate", "rationale": "там прогноз"}, '
        '"decision_type": "call_tool", "reason": "Открываю сайт", '
        '"tool_call": {"tool_name": "browser.navigate", '
        '"input_data": {"url": "https://x"}, "reason": "go"}}'
    )

    decision = _parse_agent_loop_decision(content)

    assert decision.thought is not None
    assert decision.thought.understanding == "Нужна погода"
    assert decision.thought.missing_info == "нет данных"
    assert decision.thought.planned_actions == ["открыть сайт"]
    assert decision.thought.chosen_tool == "browser.navigate"
    assert decision.thought.why == "там прогноз"


def test_require_thought_raises_when_missing() -> None:
    """Решение без thought.understanding не проходит обязательный этап THINK."""
    decision = SupervisorDecision(
        decision_type=SupervisorDecisionType.FINISH_SUCCESS,
        reason="Готово",
        final_message="Ответ",
    )

    try:
        _require_thought(decision)
    except LLMInvalidJSONError as exc:
        assert "THINK" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("_require_thought должен был бросить исключение")


def test_require_thought_passes_with_understanding() -> None:
    """Решение с непустым understanding проходит этап THINK."""
    decision = SupervisorDecision(
        decision_type=SupervisorDecisionType.FINISH_SUCCESS,
        reason="Готово",
        final_message="Ответ",
        thought=AgentThought(understanding="Задача понятна"),
    )

    _require_thought(decision)


def test_decide_enforces_think_stage_via_planner() -> None:
    """decide() отклоняет ответ LLM без блока THINK (сработает retry в runtime)."""
    from agent_desktop_constructor.builder.agent_builder import AgentBuilder
    from agent_desktop_constructor.core.models.runtime_state import (
        AgentRunStatus,
        AgentRuntimeState,
    )

    catalog = load_tools_catalog()
    agent_spec = AgentBuilder().build_from_request("проверь сегодняшнюю погоду")
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={"user_request": "погода"},
    )
    no_think = '{"decision_type": "finish_success", "reason": "ok", "final_message": "x"}'
    planner = LLMAgentLoopPlanner(_FakeLLMClient(no_think), catalog)

    try:
        planner.decide(agent_spec, state)
    except LLMInvalidJSONError as exc:
        assert "THINK" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("decide должен требовать этап THINK")

    with_think = (
        '{"thought": {"understanding": "Нужна погода"}, '
        '"decision_type": "finish_success", "reason": "ok", '
        '"final_message": "Сегодня ясно"}'
    )
    planner_ok = LLMAgentLoopPlanner(_FakeLLMClient(with_think), catalog)
    decision = planner_ok.decide(agent_spec, state)

    assert decision.decision_type == SupervisorDecisionType.FINISH_SUCCESS
    assert decision.thought.understanding == "Нужна погода"


def test_thought_synonym_thinking_key_is_accepted() -> None:
    """Синоним ключа (thinking) тоже собирается в thought."""
    content = (
        '{"thinking": {"understood": "Задача ясна"}, '
        '"decision_type": "finish_success", "reason": "Готово", '
        '"final_message": "Ответ"}'
    )

    decision = _parse_agent_loop_decision(content)

    assert decision.thought is not None
    assert decision.thought.understanding == "Задача ясна"
