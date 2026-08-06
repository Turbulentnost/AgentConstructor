"""Тесты гарантии excel.* при прикреплении файлов."""

from __future__ import annotations

from agent_desktop_constructor.app.core.attachment_tools import (
    attachments_need_excel,
    ensure_attachment_tools,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder


def test_attachments_need_excel_detects_xlsx() -> None:
    assert attachments_need_excel(["C:/tmp/report.xlsx"]) is True
    assert attachments_need_excel(["notes.txt"]) is False
    assert attachments_need_excel(None) is False


def test_ensure_attachment_tools_adds_excel_permissions() -> None:
    """При вложениях в AgentSpec появляются excel.* инструменты."""
    agent = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    before = agent.allowed_tool_names()
    updated = ensure_attachment_tools(
        agent,
        attachment_paths=["C:/data/sales.xlsx"],
    )
    after = updated.allowed_tool_names()
    assert "excel.list_files" in after
    assert "excel.read_workbook" in after
    assert "excel.create_workbook" in after
    assert "excel.edit_workbook" in after
    # Повторный вызов не дублирует.
    again = ensure_attachment_tools(
        updated,
        attached_files=[{"name": "sales.xlsx", "content": "..."}],
    )
    assert len(again.tools) == len(updated.tools)
    assert before.isdisjoint({"excel.list_files"}) or "excel.list_files" in before


def test_ensure_attachment_tools_noop_without_files() -> None:
    agent = AgentBuilder().build_from_request(
        "Посмотри совещания в Outlook и подскажи как распланировать график"
    )
    updated = ensure_attachment_tools(agent, attachment_paths=[])
    assert updated is agent
