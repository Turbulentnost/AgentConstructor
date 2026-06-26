"""Fake-инструменты MVP для агента контроля поручений."""

from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.registry import ToolRegistry


class FakeOutlookSearchMailTool(BaseTool):
    """Fake-поиск писем Outlook, которые могут содержать поручения."""

    def __init__(self) -> None:
        """Создать fake-инструмент поиска писем."""
        super().__init__(
            ToolDefinition(
                name="outlook.search_mail",
                title="Поиск писем Outlook",
                description="Имитирует поиск писем Outlook, которые могут содержать поручения.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть стабильный список fake-писем."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "messages": [
                    {
                        "id": "mail-1",
                        "subject": "Подготовить отчёт по поручениям",
                        "sender": "Иванов И.И.",
                        "received_at": "2026-06-25T09:15:00",
                        "body_preview": "Прошу подготовить отчёт по поручениям к пятнице.",
                    },
                    {
                        "id": "mail-2",
                        "subject": "Согласование документа",
                        "sender": "Петров П.П.",
                        "received_at": "2026-06-24T14:30:00",
                        "body_preview": "Нужно проверить документ и дать замечания.",
                    },
                ],
            },
        )


class FakeOutlookReadCalendarTool(BaseTool):
    """Fake-чтение календаря Outlook."""

    def __init__(self) -> None:
        """Создать fake-инструмент чтения календаря."""
        super().__init__(
            ToolDefinition(
                name="outlook.read_calendar",
                title="Чтение календаря Outlook",
                description="Имитирует чтение календаря Outlook.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={
                    "type": "object",
                    "properties": {
                        "events": {"type": "array"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть стабильный список fake-событий календаря."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "events": [
                    {
                        "id": "event-1",
                        "title": "Совещание по качеству",
                        "start_at": "2026-06-25T11:00:00",
                        "participants": ["Иванов И.И.", "Петров П.П."],
                        "description": "Обсудить статус поручений и подготовку документов.",
                    }
                ],
            },
        )


class FakeOutlookReadTasksTool(BaseTool):
    """Fake-чтение задач пользователя."""

    def __init__(self) -> None:
        """Создать fake-инструмент чтения задач."""
        super().__init__(
            ToolDefinition(
                name="outlook.read_tasks",
                title="Чтение задач Outlook",
                description="Имитирует чтение задач пользователя.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={
                    "type": "object",
                    "properties": {
                        "tasks": {"type": "array"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть стабильный список fake-задач."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Проверить статус поручений",
                        "due_date": "2026-06-27",
                        "status": "in_progress",
                    }
                ],
            },
        )


class FakeReportBuildTaskReportTool(BaseTool):
    """Fake-формирование отчёта по найденным поручениям."""

    def __init__(self) -> None:
        """Создать fake-инструмент формирования отчёта."""
        super().__init__(
            ToolDefinition(
                name="report.build_task_report",
                title="Формирование отчёта по поручениям",
                description="Формирует тестовый отчёт по найденным поручениям.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={
                    "type": "object",
                    "properties": {
                        "report_text": {"type": "string"},
                        "task_count": {"type": "integer"},
                        "risk_count": {"type": "integer"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть стабильный fake-отчёт по поручениям."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "report_text": "Отчёт по поручениям: найдено 3 потенциальных поручения. Есть 1 риск просрочки.",
                "task_count": 3,
                "risk_count": 1,
            },
        )


class FakeEmailCreateDraftTool(BaseTool):
    """Fake-создание черновика письма с отчётом."""

    def __init__(self) -> None:
        """Создать fake-инструмент создания черновика письма."""
        super().__init__(
            ToolDefinition(
                name="email.create_draft",
                title="Создание черновика письма",
                description="Имитирует создание черновика письма с отчётом.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть стабильный fake-черновик письма."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "draft_id": "draft-1",
                "subject": "Отчёт по поручениям",
                "body_preview": "Отчёт по поручениям: найдено 3 потенциальных поручения.",
            },
        )


class FakeEmailSendTool(BaseTool):
    """Fake-отправка письма, всегда требующая подтверждения человека."""

    def __init__(self) -> None:
        """Создать fake-инструмент отправки письма."""
        super().__init__(
            ToolDefinition(
                name="email.send",
                title="Отправка письма",
                description="Имитирует отправку письма. Опасное действие, всегда требует подтверждения.",
                side_effect_level=ToolSideEffectLevel.DANGEROUS,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=True,
                input_schema={"type": "object"},
                output_schema={
                    "type": "object",
                    "properties": {
                        "sent": {"type": "boolean"},
                        "message_id": {"type": "string"},
                    },
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть stable fake-результат отправки без реальной отправки письма."""
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "sent": True,
                "message_id": "sent-1",
            },
        )


def register_fake_task_control_tools(registry: ToolRegistry) -> None:
    """Зарегистрировать fake-инструменты MVP агента контроля поручений."""
    registry.register(FakeOutlookSearchMailTool())
    registry.register(FakeOutlookReadCalendarTool())
    registry.register(FakeOutlookReadTasksTool())
    registry.register(FakeReportBuildTaskReportTool())
    registry.register(FakeEmailCreateDraftTool())
    registry.register(FakeEmailSendTool())
