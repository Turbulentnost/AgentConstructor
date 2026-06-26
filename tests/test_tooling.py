"""Тесты моделей описания инструментов."""

import pytest
from pydantic import ValidationError

from agent_desktop_constructor.core.models.tooling import (
    ToolCallRequest,
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)


def make_tool_definition(
    *,
    name: str = "fake.read",
    title: str = "Fake Read",
    description: str = "Безопасный тестовый инструмент чтения.",
    side_effect_level: ToolSideEffectLevel = ToolSideEffectLevel.READ,
    execution_mode: ToolExecutionMode = ToolExecutionMode.LOCAL,
    requires_human_approval: bool = False,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> ToolDefinition:
    """Создать тестовый паспорт инструмента."""
    return ToolDefinition(
        name=name,
        title=title,
        description=description,
        side_effect_level=side_effect_level,
        execution_mode=execution_mode,
        requires_human_approval=requires_human_approval,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        input_schema={},
        output_schema={},
    )


def test_read_tool_definition_can_be_created() -> None:
    """ToolDefinition создается для read-инструмента."""
    definition = make_tool_definition()

    assert definition.side_effect_level == ToolSideEffectLevel.READ


def test_create_draft_tool_definition_can_be_created() -> None:
    """ToolDefinition создается для create_draft-инструмента."""
    definition = make_tool_definition(
        name="fake.create_draft",
        side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
    )

    assert definition.side_effect_level == ToolSideEffectLevel.CREATE_DRAFT


def test_dangerous_tool_definition_can_be_created_with_approval() -> None:
    """Dangerous ToolDefinition создается только с requires_human_approval=True."""
    definition = make_tool_definition(
        name="fake.dangerous",
        side_effect_level=ToolSideEffectLevel.DANGEROUS,
        requires_human_approval=True,
    )

    assert definition.requires_human_approval is True


def test_dangerous_tool_definition_without_approval_raises_error() -> None:
    """Dangerous ToolDefinition без approval вызывает ValidationError."""
    with pytest.raises(ValidationError, match="requires_human_approval"):
        make_tool_definition(side_effect_level=ToolSideEffectLevel.DANGEROUS)


@pytest.mark.parametrize("timeout_seconds", [0, -1])
def test_non_positive_timeout_seconds_raises_error(timeout_seconds: int) -> None:
    """timeout_seconds меньше или равный нулю вызывает ValidationError."""
    with pytest.raises(ValidationError):
        make_tool_definition(timeout_seconds=timeout_seconds)


def test_negative_max_retries_raises_error() -> None:
    """max_retries меньше нуля вызывает ValidationError."""
    with pytest.raises(ValidationError):
        make_tool_definition(max_retries=-1)


def test_empty_name_raises_error() -> None:
    """Пустой name вызывает ValidationError."""
    with pytest.raises(ValidationError, match="name"):
        make_tool_definition(name="")


def test_empty_title_raises_error() -> None:
    """Пустой title вызывает ValidationError."""
    with pytest.raises(ValidationError, match="title"):
        make_tool_definition(title="")


def test_tool_call_request_can_be_created() -> None:
    """ToolCallRequest создается."""
    request = ToolCallRequest(
        run_id="run-1",
        tool_name="fake.read",
        input_data={"query": "test"},
    )

    assert request.run_id == "run-1"


def test_successful_tool_call_result_can_be_created() -> None:
    """ToolCallResult ok=True создается."""
    result = ToolCallResult(
        ok=True,
        tool_name="fake.read",
        output_data={"value": "test"},
    )

    assert result.ok is True


def test_failed_tool_call_result_without_error_raises_error() -> None:
    """ToolCallResult ok=False без error_type и error_message вызывает ValidationError."""
    with pytest.raises(ValidationError, match="error_type"):
        ToolCallResult(ok=False, tool_name="fake.read")


def test_human_approval_result_cannot_be_successful() -> None:
    """ToolCallResult requires_human_approval=True и ok=True вызывает ValidationError."""
    with pytest.raises(ValidationError, match="ok"):
        ToolCallResult(
            ok=True,
            tool_name="fake.dangerous",
            requires_human_approval=True,
        )
