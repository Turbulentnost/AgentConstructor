"""Fake-инструменты только для тестов."""

from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool


class FakeReadTool(BaseTool):
    """Тестовый read-инструмент без внешних побочных эффектов."""

    def __init__(self) -> None:
        """Создать fake read-инструмент."""
        super().__init__(
            ToolDefinition(
                name="fake.read",
                title="Fake Read",
                description="Возвращает тестовый результат чтения.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={},
                output_schema={},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть тестовый результат чтения."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"value": "fake_read_result"},
        )


class FakeDraftTool(BaseTool):
    """Тестовый create_draft-инструмент без внешней отправки."""

    def __init__(self) -> None:
        """Создать fake draft-инструмент."""
        super().__init__(
            ToolDefinition(
                name="fake.create_draft",
                title="Fake Create Draft",
                description="Создает тестовый черновик.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={},
                output_schema={},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть тестовый идентификатор черновика."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"draft_id": "draft-1"},
        )


class FakeDangerousTool(BaseTool):
    """Тестовый dangerous-инструмент, требующий HumanApproval."""

    def __init__(self) -> None:
        """Создать fake dangerous-инструмент."""
        super().__init__(
            ToolDefinition(
                name="fake.dangerous",
                title="Fake Dangerous",
                description="Имитирует опасное действие для тестов.",
                side_effect_level=ToolSideEffectLevel.DANGEROUS,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=True,
                input_schema={},
                output_schema={},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть тестовый успешный результат опасного действия."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"done": True},
        )
