"""Каталог доступных инструментов для Builder, UI и будущего LLM Planner."""

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator

from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.tooling import (
    ToolExecutionMode,
    ToolSideEffectLevel,
)


class ToolCatalogItem(BaseModel):
    """Описание одного доступного инструмента для человека и планировщика."""

    name: str
    title: str
    description: str
    category: str
    side_effect_level: ToolSideEffectLevel
    execution_mode: ToolExecutionMode
    requires_human_approval: bool
    input_schema: dict
    output_schema: dict
    allowed_for_agent_types: list[str]
    examples: list[str]
    planner_hint: str

    @field_validator("name", "title", "description", "category", "planner_hint")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @field_validator("allowed_for_agent_types")
    @classmethod
    def validate_allowed_for_agent_types(cls, value: list[str]) -> list[str]:
        """Проверить, что список типов агентов не пустой."""
        if not value:
            raise ValueError("allowed_for_agent_types не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_dangerous_requires_approval(self) -> ToolCatalogItem:
        """Проверить, что dangerous-инструмент требует подтверждения человека."""
        if (
            self.side_effect_level == ToolSideEffectLevel.DANGEROUS
            and not self.requires_human_approval
        ):
            raise ValueError("dangerous-инструмент должен требовать HumanApproval")
        return self


class ToolsCatalog(BaseModel):
    """Источник правды о доступных инструментах проекта."""

    tools: list[ToolCatalogItem]

    @model_validator(mode="after")
    def validate_unique_tool_names(self) -> ToolsCatalog:
        """Проверить, что tool_name в каталоге уникальны."""
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("Каталог содержит duplicate tool names")
        return self

    def get_tool(self, name: str) -> ToolCatalogItem:
        """Вернуть инструмент по имени или выбросить понятную ошибку."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        raise ValueError(f"Инструмент {name!r} не найден в каталоге")

    def has_tool(self, name: str) -> bool:
        """Проверить наличие инструмента в каталоге."""
        return any(tool.name == name for tool in self.tools)

    def list_tool_names(self) -> set[str]:
        """Вернуть имена всех инструментов каталога."""
        return {tool.name for tool in self.tools}

    def list_for_agent_type(self, agent_type: str) -> list[ToolCatalogItem]:
        """Вернуть инструменты, разрешённые для типа агента."""
        return [
            tool
            for tool in self.tools
            if agent_type in tool.allowed_for_agent_types
        ]

    def to_planner_context(self, agent_type: str | None = None) -> str:
        """Сформировать русскоязычный контекст доступных инструментов для LLM."""
        tools = (
            self.list_for_agent_type(agent_type)
            if agent_type is not None
            else self.tools
        )
        lines = ["Доступные инструменты:"]
        for index, tool in enumerate(tools, start=1):
            approval_text = "да" if tool.requires_human_approval else "нет"
            example_text = "; ".join(tool.examples) if tool.examples else "нет примеров"
            lines.extend(
                [
                    f"{index}. {tool.name}",
                    f"Назначение: {tool.description}",
                    f"Категория: {tool.category}",
                    f"Уровень действия: {tool.side_effect_level.value}",
                    f"Требует подтверждения: {approval_text}",
                    f"Когда использовать: {tool.planner_hint}",
                    f"Пример: {example_text}",
                ]
            )
        lines.append(
            "Используй только инструменты из этого списка. Не придумывай новые tool_name. "
            "Если подходящего инструмента нет, верни needs_human_or_new_tool=true."
        )
        return "\n".join(lines)

    def validate_tool_names(self, tool_names: list[str]) -> None:
        """Проверить, что все имена инструментов есть в каталоге."""
        unknown_tool_names = [
            tool_name for tool_name in tool_names if not self.has_tool(tool_name)
        ]
        if unknown_tool_names:
            raise ValueError(
                "Неизвестные tool_name: " + ", ".join(sorted(unknown_tool_names))
            )


def validate_agent_spec_tools_against_catalog(
    agent_spec: AgentSpec,
    catalog: ToolsCatalog,
) -> None:
    """Проверить, что AgentSpec не содержит инструментов вне каталога."""
    tool_names = [tool.tool_name for tool in agent_spec.tools]
    node_tool_names = [
        node.tool_name for node in agent_spec.graph_nodes if node.tool_name is not None
    ]
    catalog.validate_tool_names(tool_names + node_tool_names)
