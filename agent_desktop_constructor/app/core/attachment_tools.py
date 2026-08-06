"""Гарантировать инструменты для обработки прикреплённых файлов в AgentSpec."""

from __future__ import annotations

from pathlib import Path

from agent_desktop_constructor.core.models.agent_spec import (
    AgentActionLevel,
    AgentSpec,
    AgentToolPermission,
)

# Минимальный набор, чтобы агент мог увидеть и обработать Excel/файлы workspace.
_EXCEL_TOOLS: tuple[tuple[str, AgentActionLevel, bool], ...] = (
    ("excel.list_files", AgentActionLevel.READ, False),
    ("excel.read_workbook", AgentActionLevel.READ, False),
    ("excel.create_workbook", AgentActionLevel.CREATE_DRAFT, False),
    ("excel.edit_workbook", AgentActionLevel.CREATE_DRAFT, False),
)

_EXCEL_SUFFIXES = {".xlsx"}


def attachments_need_excel(paths_or_names: list[str] | None) -> bool:
    """True, если среди вложений есть Excel (по пути или имени)."""
    if not paths_or_names:
        return False
    for item in paths_or_names:
        name = str(item or "").strip()
        if not name:
            continue
        if Path(name).suffix.lower() in _EXCEL_SUFFIXES:
            return True
    return False


def ensure_attachment_tools(
    agent_spec: AgentSpec,
    *,
    attachment_paths: list[str] | None = None,
    attached_files: list[dict] | None = None,
) -> AgentSpec:
    """Добавить excel.* в AgentSpec, если прикреплены файлы (особенно .xlsx).

    Если вложений нет — возвращает исходный spec без изменений.
    """
    names: list[str] = []
    if attachment_paths:
        names.extend(attachment_paths)
    if attached_files:
        for item in attached_files:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
    if not names:
        return agent_spec

    # При любых вложениях даём excel.*: list/read для входящих .xlsx,
    # create/edit — чтобы сохранить результат обработки.
    existing = {tool.tool_name for tool in agent_spec.tools if tool.allowed}
    additions: list[AgentToolPermission] = []
    for tool_name, level, needs_approval in _EXCEL_TOOLS:
        if tool_name in existing:
            continue
        # list_files полезен для любых вложений; create/edit — всегда полезны
        # рядом с read, чтобы агент мог сохранить результат.
        additions.append(
            AgentToolPermission(
                tool_name=tool_name,
                action_level=level,
                requires_human_approval=needs_approval,
                allowed=True,
            )
        )
    if not additions:
        return agent_spec
    return agent_spec.model_copy(update={"tools": list(agent_spec.tools) + additions})
