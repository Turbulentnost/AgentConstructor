"""Pydantic-модели проверяемой спецификации ИИ-агента."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class AgentActionLevel(StrEnum):
    """Уровень риска действия, которое может выполнить инструмент агента."""

    READ = "read"
    CREATE_DRAFT = "create_draft"
    WRITE = "write"
    DANGEROUS = "dangerous"


class HumanApprovalPolicy(StrEnum):
    """Общая политика привлечения человека к выполнению агента."""

    NEVER = "never"
    ON_LOW_CONFIDENCE = "on_low_confidence"
    BEFORE_WRITE = "before_write"
    ALWAYS = "always"


class AgentGoal(BaseModel):
    """Цель агента, критерии успеха и явно запрещенные действия."""

    main_goal: str
    success_criteria: list[str]
    forbidden_actions: list[str]

    @field_validator("main_goal")
    @classmethod
    def validate_main_goal(cls, value: str) -> str:
        """Проверить, что основная цель агента заполнена."""
        if not value.strip():
            raise ValueError("main_goal не должен быть пустым")
        return value


class AgentDataRequirement(BaseModel):
    """Данные, которые нужны агенту для выполнения задачи."""

    name: str
    description: str
    source_type: str
    required: bool
    can_agent_find: bool
    default_value: str | None
    ask_human_if_missing: bool

    @field_validator("name", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @model_validator(mode="after")
    def validate_missing_required_data_policy(self) -> AgentDataRequirement:
        """Проверить, что недостающие обязательные данные будут запрошены у человека."""
        needs_human_input = (
            self.required
            and not self.can_agent_find
            and self.default_value is None
        )
        if needs_human_input and not self.ask_human_if_missing:
            raise ValueError(
                "Если обязательные данные нельзя найти автоматически и нет значения "
                "по умолчанию, ask_human_if_missing должен быть True"
            )
        return self


class AgentToolPermission(BaseModel):
    """Разрешение агента на использование конкретного инструмента."""

    tool_name: str
    action_level: AgentActionLevel
    requires_human_approval: bool
    allowed: bool

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        """Проверить, что имя инструмента заполнено."""
        if not value.strip():
            raise ValueError("tool_name не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_dangerous_tool_requires_approval(self) -> AgentToolPermission:
        """Проверить, что dangerous-инструмент требует HumanApproval."""
        if (
            self.action_level == AgentActionLevel.DANGEROUS
            and not self.requires_human_approval
        ):
            raise ValueError(
                "dangerous tool всегда должен иметь requires_human_approval=True"
            )
        return self


class AgentGraphNodeType(StrEnum):
    """Тип узла в графе работы агента."""

    VALIDATION = "validation"
    PLANNING = "planning"
    DATA_SEARCH = "data_search"
    TOOL_CALL = "tool_call"
    ANALYSIS = "analysis"
    ROUTING = "routing"
    HUMAN_REVIEW = "human_review"
    FINAL = "final"


class AgentGraphNode(BaseModel):
    """Один шаг графа работы агента."""

    node_id: str
    node_type: AgentGraphNodeType
    title: str
    description: str
    tool_name: str | None
    next_on_success: str | None
    next_on_error: str | None
    requires_human_approval: bool

    @field_validator("node_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле узла заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @model_validator(mode="after")
    def validate_tool_call_has_tool_name(self) -> AgentGraphNode:
        """Проверить, что tool_call-узел ссылается на инструмент."""
        if self.node_type == AgentGraphNodeType.TOOL_CALL and not self.tool_name:
            raise ValueError("Для node_type == tool_call поле tool_name обязательно")
        return self


class AgentRuntimeLimits(BaseModel):
    """Лимиты выполнения агента для защиты от бесконечных циклов и лишних вызовов."""

    max_steps: int = Field(default=20, gt=0)
    max_tool_calls: int = Field(default=30, gt=0)
    max_retries_per_tool: int = Field(default=2, ge=0)
    low_confidence_threshold: float = Field(default=0.65, ge=0, le=1)


class AgentSpec(BaseModel):
    """Полное проверяемое описание агента для Builder, UI, Storage и Runtime."""

    agent_id: str
    name: str
    description: str
    goal: AgentGoal
    data_requirements: list[AgentDataRequirement]
    tools: list[AgentToolPermission]
    graph_nodes: list[AgentGraphNode] = Field(min_length=1)
    runtime_limits: AgentRuntimeLimits

    @field_validator("agent_id", "name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле спецификации заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> AgentSpec:
        """Проверить согласованность графа, инструментов и переходов."""
        node_ids = [node.node_id for node in self.graph_nodes]
        unique_node_ids = set(node_ids)
        if len(node_ids) != len(unique_node_ids):
            raise ValueError("node_id должны быть уникальными")

        tool_names = {tool.tool_name for tool in self.tools}
        for node in self.graph_nodes:
            if node.node_type == AgentGraphNodeType.TOOL_CALL and not node.tool_name:
                raise ValueError("Для tool_call-узла tool_name обязателен")
            if node.tool_name is not None and node.tool_name not in tool_names:
                raise ValueError(
                    f"Инструмент {node.tool_name!r} не описан в tools"
                )
            self._validate_transition(node.next_on_success, unique_node_ids)
            self._validate_transition(node.next_on_error, unique_node_ids)

        has_final_node = any(
            node.node_type == AgentGraphNodeType.FINAL for node in self.graph_nodes
        )
        if not has_final_node:
            raise ValueError("В графе должен быть хотя бы один final-узел")

        return self

    @staticmethod
    def _validate_transition(node_id: str | None, existing_node_ids: set[str]) -> None:
        """Проверить, что переход ссылается на существующий узел."""
        if node_id is not None and node_id not in existing_node_ids:
            raise ValueError(f"Переход ссылается на неизвестный node_id: {node_id}")

    def get_start_node(self) -> AgentGraphNode:
        """Вернуть стартовый узел графа; в MVP это первый узел списка."""
        return self.graph_nodes[0]

    def get_node(self, node_id: str) -> AgentGraphNode:
        """Вернуть узел по идентификатору или выбросить понятную ошибку."""
        for node in self.graph_nodes:
            if node.node_id == node_id:
                return node
        raise ValueError(f"Узел с node_id={node_id!r} не найден")

    def required_human_inputs(self) -> list[AgentDataRequirement]:
        """Вернуть требования к данным, которые нужно запросить у человека."""
        return [
            requirement
            for requirement in self.data_requirements
            if requirement.ask_human_if_missing
        ]

    def allowed_tool_names(self) -> set[str]:
        """Вернуть имена инструментов, разрешенных для агента."""
        return {tool.tool_name for tool in self.tools if tool.allowed}
