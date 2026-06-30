"""Тесты моделей LLM Supervisor."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.app.llm.supervisor_models import (
    SupervisorDecision,
    SupervisorDecisionType,
    SupervisorToolCallProposal,
)


def test_supervisor_decision_validates_continue() -> None:
    """SupervisorDecision валидируется для continue_to_next."""
    decision = SupervisorDecision(
        decision_type=SupervisorDecisionType.CONTINUE_TO_NEXT,
        reason="Можно идти дальше",
        confidence=0.8,
    )

    assert decision.decision_type == SupervisorDecisionType.CONTINUE_TO_NEXT


def test_call_additional_tool_requires_tool_call() -> None:
    """call_additional_tool требует tool_call."""
    with pytest.raises(ValidationError):
        SupervisorDecision(
            decision_type=SupervisorDecisionType.CALL_ADDITIONAL_TOOL,
            reason="Нужны данные",
        )


def test_ask_human_requires_question() -> None:
    """ask_human требует human_question."""
    with pytest.raises(ValidationError):
        SupervisorDecision(
            decision_type=SupervisorDecisionType.ASK_HUMAN,
            reason="Нужно уточнение",
        )


def test_tool_call_proposal_requires_non_empty_text() -> None:
    """tool_name и reason не должны быть пустыми."""
    with pytest.raises(ValidationError):
        SupervisorToolCallProposal(tool_name="", input_data={}, reason="")

