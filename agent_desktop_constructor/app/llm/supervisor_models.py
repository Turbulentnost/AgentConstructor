"""Pydantic-модели решений LLM Supervisor."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class SupervisorDecisionType(StrEnum):
    """Тип решения LLM Supervisor после события Runtime."""

    CONTINUE_TO_NEXT = "continue_to_next"
    RETRY_TOOL = "retry_tool"
    CALL_TOOL = "call_tool"
    CALL_ADDITIONAL_TOOL = "call_additional_tool"
    ASK_HUMAN = "ask_human"
    REQUEST_CREDENTIALS = "request_credentials"
    REPLAN_GRAPH = "replan_graph"
    FINISH_SUCCESS = "finish_success"
    FINISH_FAILED = "finish_failed"


class SupervisorToolCallProposal(BaseModel):
    """Предложение Supervisor вызвать дополнительный tool через Runtime."""

    tool_name: str
    input_data: dict
    reason: str

    @field_validator("tool_name", "reason")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что строковое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value


class SupervisorDecision(BaseModel):
    """Структурированное решение Supervisor для безопасного применения Runtime."""

    decision_type: SupervisorDecisionType
    reason: str
    next_node_id: str | None = None
    tool_call: SupervisorToolCallProposal | None = None
    human_question: str | None = None
    human_options: list[str] = Field(default_factory=list)
    graph_patch: dict | None = None
    final_message: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        """Проверить, что reason заполнен."""
        if not value.strip():
            raise ValueError("reason не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_decision_payload(self) -> SupervisorDecision:
        """Проверить обязательные поля для отдельных типов решений."""
        if (
            self.decision_type
            in {
                SupervisorDecisionType.CALL_TOOL,
                SupervisorDecisionType.CALL_ADDITIONAL_TOOL,
            }
            and self.tool_call is None
        ):
            raise ValueError("call_tool требует tool_call")
        if self.decision_type == SupervisorDecisionType.ASK_HUMAN:
            if self.human_question is None or not self.human_question.strip():
                raise ValueError("ask_human требует human_question")
        if (
            self.decision_type == SupervisorDecisionType.FINISH_SUCCESS
            and (self.final_message is None or not self.final_message.strip())
        ):
            raise ValueError("finish_success требует final_message")
        if (
            self.decision_type == SupervisorDecisionType.REPLAN_GRAPH
            and self.graph_patch is None
        ):
            raise ValueError("replan_graph требует graph_patch")
        return self

