"""Тесты моделей состояния выполнения агента."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
    HumanApprovalRequest,
)


def make_state(
    *,
    status: AgentRunStatus = AgentRunStatus.CREATED,
    step_counter: int = 0,
    tool_call_counter: int = 0,
) -> AgentRuntimeState:
    """Создать тестовое состояние запуска агента."""
    return AgentRuntimeState(
        run_id="run-1",
        agent_id="agent-1",
        status=status,
        step_counter=step_counter,
        tool_call_counter=tool_call_counter,
    )


def make_approval_request() -> HumanApprovalRequest:
    """Создать тестовый запрос HumanApproval."""
    return HumanApprovalRequest(
        approval_id="approval-1",
        node_id="send_report",
        tool_name="email.send",
        question="Агент хочет отправить письмо. Подтвердить отправку?",
        options=["Подтвердить", "Отклонить"],
        status="pending",
    )


def test_agent_runtime_state_can_be_created() -> None:
    """AgentRuntimeState создается."""
    state = make_state()

    assert state.run_id == "run-1"
    assert state.status == AgentRunStatus.CREATED


def test_run_id_cannot_be_empty() -> None:
    """run_id не может быть пустым."""
    with pytest.raises(ValidationError, match="run_id"):
        AgentRuntimeState(run_id="", agent_id="agent-1", status=AgentRunStatus.CREATED)


def test_agent_id_cannot_be_empty() -> None:
    """agent_id не может быть пустым."""
    with pytest.raises(ValidationError, match="agent_id"):
        AgentRuntimeState(run_id="run-1", agent_id="", status=AgentRunStatus.CREATED)


def test_add_tool_result_adds_record() -> None:
    """add_tool_result добавляет запись."""
    state = make_state()

    state.add_tool_result(
        tool_name="fake.read",
        input_data={"query": "x"},
        output_data={"value": "y"},
        ok=True,
    )

    assert len(state.tool_results) == 1
    assert state.tool_results[0].tool_name == "fake.read"


def test_add_tool_result_increments_tool_call_counter() -> None:
    """add_tool_result увеличивает tool_call_counter."""
    state = make_state()

    state.add_tool_result("fake.read", {}, {}, True)

    assert state.tool_call_counter == 1


def test_add_error_adds_error() -> None:
    """add_error добавляет ошибку."""
    state = make_state()

    state.add_error("Ошибка шага")

    assert state.errors == ["Ошибка шага"]


def test_pause_for_human_changes_status() -> None:
    """pause_for_human меняет статус на paused_for_human."""
    state = make_state(status=AgentRunStatus.RUNNING)

    state.pause_for_human(make_approval_request())

    assert state.status == AgentRunStatus.PAUSED_FOR_HUMAN


def test_pause_for_human_stores_pending_approval() -> None:
    """pause_for_human сохраняет pending_human_approval."""
    state = make_state(status=AgentRunStatus.RUNNING)
    request = make_approval_request()

    state.pause_for_human(request)

    assert state.pending_human_approval == request


def test_resume_after_human_without_pending_approval_raises_error() -> None:
    """resume_after_human без pending_human_approval вызывает ValueError."""
    state = make_state(status=AgentRunStatus.RUNNING)

    with pytest.raises(ValueError, match="HumanApproval"):
        state.resume_after_human("Подтвердить")


def test_resume_after_human_stores_decision_in_variables() -> None:
    """resume_after_human сохраняет решение в variables['human_decisions'].""" 
    state = make_state(status=AgentRunStatus.RUNNING)
    state.pause_for_human(make_approval_request())

    state.resume_after_human("Подтвердить", comment="Можно отправлять")

    decisions = state.variables["human_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["selected_option"] == "Подтвердить"
    assert decisions[0]["comment"] == "Можно отправлять"
    assert state.pending_human_approval is None


def test_resume_after_human_changes_status_to_running() -> None:
    """resume_after_human переводит статус в running."""
    state = make_state(status=AgentRunStatus.RUNNING)
    state.pause_for_human(make_approval_request())

    state.resume_after_human("Подтвердить")

    assert state.status == AgentRunStatus.RUNNING


def test_can_continue_returns_true_for_running_within_limits() -> None:
    """can_continue возвращает True для running в пределах лимитов."""
    state = make_state(status=AgentRunStatus.RUNNING)

    assert state.can_continue(max_steps=10, max_tool_calls=10) is True


def test_can_continue_returns_false_when_max_steps_reached() -> None:
    """can_continue возвращает False при превышении max_steps."""
    state = make_state(status=AgentRunStatus.RUNNING, step_counter=10)

    assert state.can_continue(max_steps=10, max_tool_calls=20) is False


def test_can_continue_returns_false_when_max_tool_calls_reached() -> None:
    """can_continue возвращает False при превышении max_tool_calls."""
    state = make_state(status=AgentRunStatus.RUNNING, tool_call_counter=20)

    assert state.can_continue(max_steps=30, max_tool_calls=20) is False


def test_can_continue_returns_false_when_paused_for_human() -> None:
    """can_continue возвращает False при paused_for_human."""
    state = make_state(status=AgentRunStatus.RUNNING)
    state.pause_for_human(make_approval_request())

    assert state.can_continue(max_steps=10, max_tool_calls=10) is False


def test_mark_completed_changes_status() -> None:
    """mark_completed меняет статус."""
    state = make_state(status=AgentRunStatus.RUNNING)

    state.mark_completed()

    assert state.status == AgentRunStatus.COMPLETED


def test_mark_failed_changes_status_and_adds_error() -> None:
    """mark_failed меняет статус и добавляет ошибку."""
    state = make_state(status=AgentRunStatus.RUNNING)

    state.mark_failed("Ошибка выполнения")

    assert state.status == AgentRunStatus.FAILED
    assert state.errors == ["Ошибка выполнения"]


def test_mark_cancelled_changes_status() -> None:
    """mark_cancelled меняет статус."""
    state = make_state(status=AgentRunStatus.RUNNING)

    state.mark_cancelled("Пользователь отменил")

    assert state.status == AgentRunStatus.CANCELLED
    assert state.variables["cancel_reason"] == "Пользователь отменил"


def test_state_can_be_serialized_and_restored_with_pydantic() -> None:
    """Состояние сериализуется и восстанавливается через Pydantic."""
    state = make_state(status=AgentRunStatus.RUNNING)
    state.mark_running("read_mail")
    state.add_tool_result("fake.read", {"query": "x"}, {"value": "y"}, True)
    state.pause_for_human(make_approval_request())

    dumped = state.model_dump(mode="json")
    restored = AgentRuntimeState.model_validate(dumped)

    assert restored == state
    assert restored.pending_human_approval is not None
    assert restored.tool_results[0].output_data == {"value": "y"}
