"""Тесты Excel-инструментов и изолированной рабочей папки агента."""

import pytest

from agent_desktop_constructor.tools.agent_workspace import (
    AgentWorkspaceResolver,
    WorkspaceError,
)
from agent_desktop_constructor.tools.excel_tools import register_excel_tools
from agent_desktop_constructor.tools.registry import ToolRegistry


@pytest.fixture
def registry(tmp_path):
    """Реестр с Excel-инструментами и tmp-корнем рабочих папок."""
    reg = ToolRegistry()
    register_excel_tools(reg, AgentWorkspaceResolver(tmp_path))
    return reg


def _ctx(agent_id: str = "agent-1", **extra) -> dict:
    """Собрать input_data с runtime_context.agent_id."""
    return {"runtime_context": {"agent_id": agent_id}, **extra}


def test_create_read_edit_roundtrip(registry) -> None:
    """Создание, чтение и редактирование .xlsx работают в папке агента."""
    create = registry.get("excel.create_workbook").execute(
        _ctx(filename="report", headers=["A", "B"], rows=[[1, 2], [3, 4]])
    )
    assert create.ok is True

    read = registry.get("excel.read_workbook").execute(_ctx(filename="report"))
    assert read.ok is True
    assert read.output_data["rows"] == [["A", "B"], [1, 2], [3, 4]]

    edit = registry.get("excel.edit_workbook").execute(
        _ctx(
            filename="report",
            operations=[
                {"action": "append_row", "values": [5, 6]},
                {"action": "set_cell", "cell": "A1", "value": "X"},
            ],
        )
    )
    assert edit.ok is True

    read2 = registry.get("excel.read_workbook").execute(_ctx(filename="report"))
    assert read2.output_data["rows"][0][0] == "X"
    assert [5, 6] in read2.output_data["rows"]


def test_create_refuses_overwrite_without_flag(registry) -> None:
    """Повторное создание без overwrite возвращает ошибку FILE_EXISTS."""
    registry.get("excel.create_workbook").execute(_ctx(filename="data"))
    second = registry.get("excel.create_workbook").execute(_ctx(filename="data"))
    assert second.ok is False
    assert second.error_type == "FILE_EXISTS"


def test_read_missing_file_returns_error(registry) -> None:
    """Чтение несуществующего файла возвращает ошибку рабочей папки."""
    result = registry.get("excel.read_workbook").execute(_ctx(filename="nope"))
    assert result.ok is False
    assert result.error_type == "WORKSPACE_ERROR"


def test_each_agent_has_isolated_folder(registry, tmp_path) -> None:
    """Файлы одного агента не видны другому агенту."""
    registry.get("excel.create_workbook").execute(_ctx("agent-a", filename="a"))
    listed_b = registry.get("excel.list_files").execute(_ctx("agent-b"))
    assert listed_b.output_data["count"] == 0


def test_workspace_blocks_path_traversal(tmp_path) -> None:
    """Резолвер не даёт выйти за пределы папки агента."""
    workspace = AgentWorkspaceResolver(tmp_path).for_agent("agent-1")
    with pytest.raises(WorkspaceError):
        workspace.resolve("../../secret.xlsx")


def test_ingest_attachment_copies_and_reads(tmp_path) -> None:
    """Прикреплённый .xlsx копируется в папку агента и читается в текст."""
    from openpyxl import Workbook

    from agent_desktop_constructor.tools.attachment_reader import ingest_attachment

    source = tmp_path / "src.xlsx"
    workbook = Workbook()
    workbook.active.append(["Задача", "Срок"])
    workbook.active.append(["Отчёт", "2026-07-10"])
    workbook.save(source)
    workbook.close()

    workspace = AgentWorkspaceResolver(tmp_path / "ws").for_agent("agent-1")
    result = ingest_attachment(workspace, str(source))

    assert result["name"] == "src.xlsx"
    assert "Задача" in result["content"]
    assert (workspace.directory / "src.xlsx").exists()
