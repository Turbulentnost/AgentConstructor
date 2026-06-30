"""Pydantic-модели состояния конкретного запуска агента."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class AgentRunStatus(StrEnum):
    """Статус конкретного запуска агента."""

    CREATED = "created"
    RUNNING = "running"
    PAUSED_FOR_HUMAN = "paused_for_human"
    PAUSED_FOR_CREDENTIALS = "paused_for_credentials"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepStatus(StrEnum):
    """Статус отдельного шага графа агента."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolCallRecord(BaseModel):
    """Запись результата вызова инструмента внутри состояния агента."""

    tool_name: str
    input_data: dict
    output_data: dict | None = None
    ok: bool
    error_type: str | None = None
    error_message: str | None = None

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        """Проверить, что имя инструмента заполнено."""
        if not value.strip():
            raise ValueError("tool_name не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_error_details(self) -> ToolCallRecord:
        """Проверить, что ошибочный результат содержит описание ошибки."""
        if not self.ok and not self.error_type and not self.error_message:
            raise ValueError(
                "Если ok=False, должен быть указан error_type или error_message"
            )
        return self


class HumanApprovalRequest(BaseModel):
    """Запрос к человеку, когда агент не может продолжить автоматически."""

    approval_id: str
    node_id: str
    tool_name: str | None = None
    question: str
    options: list[str]
    status: str
    selected_option: str | None = None
    comment: str | None = None

    @field_validator("approval_id", "node_id", "question", "status")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        """Проверить, что список вариантов ответа не пустой."""
        if not value:
            raise ValueError("options не должен быть пустым")
        return value


class AgentRuntimeState(BaseModel):
    """Полное состояние одного запуска агента, восстанавливаемое из Storage."""

    run_id: str
    agent_id: str
    status: AgentRunStatus
    current_node_id: str | None = None
    step_counter: int = 0
    tool_call_counter: int = 0
    variables: dict = Field(default_factory=dict)
    tool_results: list[ToolCallRecord] = Field(default_factory=list)
    pending_human_approval: HumanApprovalRequest | None = None
    errors: list[str] = Field(default_factory=list)

    @field_validator("run_id", "agent_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательный идентификатор заполнен."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    def add_tool_result(
        self,
        tool_name: str,
        input_data: dict,
        output_data: dict | None,
        ok: bool,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Добавить результат вызова инструмента и увеличить счетчик вызовов."""
        record = ToolCallRecord(
            tool_name=tool_name,
            input_data=input_data,
            output_data=output_data,
            ok=ok,
            error_type=error_type,
            error_message=error_message,
        )
        self.tool_results.append(record)
        self.tool_call_counter += 1

    def add_error(self, message: str) -> None:
        """Добавить ошибку в состояние запуска."""
        self.errors.append(message)

    def pause_for_human(self, request: HumanApprovalRequest) -> None:
        """Приостановить запуск до решения человека."""
        self.status = AgentRunStatus.PAUSED_FOR_HUMAN
        self.pending_human_approval = request

    def pause_for_credentials(self, reason: str) -> None:
        """Приостановить запуск до предоставления credentials вне LLM-контекста."""
        self.status = AgentRunStatus.PAUSED_FOR_CREDENTIALS
        self.variables["credential_request_reason"] = reason

    def resume_after_human(
        self,
        selected_option: str,
        comment: str | None = None,
    ) -> None:
        """Сохранить решение человека и возобновить выполнение."""
        if self.pending_human_approval is None:
            raise ValueError("Нет ожидающего HumanApproval-запроса")

        approval = self.pending_human_approval
        approval.selected_option = selected_option
        approval.comment = comment
        approval.status = "answered"

        decisions = self.variables.setdefault("human_decisions", [])
        decisions.append(approval.model_dump(mode="json"))

        self.pending_human_approval = None
        self.status = AgentRunStatus.RUNNING

    def can_continue(self, max_steps: int, max_tool_calls: int) -> bool:
        """Проверить, может ли запуск продолжать автоматическое выполнение."""
        return (
            self.status in {AgentRunStatus.CREATED, AgentRunStatus.RUNNING}
            and self.step_counter < max_steps
            and self.tool_call_counter < max_tool_calls
            and self.pending_human_approval is None
        )

    def mark_running(self, current_node_id: str | None = None) -> None:
        """Перевести запуск в running и при необходимости обновить текущий узел."""
        self.status = AgentRunStatus.RUNNING
        if current_node_id is not None:
            self.current_node_id = current_node_id

    def mark_completed(self) -> None:
        """Отметить запуск как успешно завершенный."""
        self.status = AgentRunStatus.COMPLETED

    def mark_failed(self, error_message: str) -> None:
        """Отметить запуск как failed и сохранить причину."""
        self.status = AgentRunStatus.FAILED
        self.errors.append(error_message)

    def mark_cancelled(self, reason: str | None = None) -> None:
        """Отметить запуск как cancelled и при наличии сохранить причину."""
        self.status = AgentRunStatus.CANCELLED
        if reason is not None:
            self.variables["cancel_reason"] = reason
