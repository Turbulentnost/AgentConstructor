"""Тесты чтения вложений для планирования."""

from __future__ import annotations

from agent_desktop_constructor.app.core.services.agent_application_service import (
    AgentApplicationService,
)
from agent_desktop_constructor.tools.attachment_reader import (
    format_attachments_for_planning,
    read_attachment_sources,
)


def test_read_attachment_sources_reads_text_file(tmp_path) -> None:
    path = tmp_path / "rules.txt"
    path.write_text("Проверять поле «Сумма»", encoding="utf-8")

    items = read_attachment_sources([str(path)])

    assert len(items) == 1
    assert items[0]["name"] == "rules.txt"
    assert "Сумма" in items[0]["content"]


def test_format_attachments_for_planning_builds_instruction_block() -> None:
    block = format_attachments_for_planning(
        [{"name": "Шаблон.xlsx", "content": "строка 1 | строка 2"}]
    )

    assert "Прикреплённые файлы" in block
    assert "инструкции при составлении плана" in block
    assert "### Шаблон.xlsx" in block
    assert "строка 1 | строка 2" in block


def test_planning_request_with_attachments_merges_text_and_files(tmp_path) -> None:
    path = tmp_path / "template.csv"
    path.write_text("col1,col2\na,b", encoding="utf-8")

    merged = AgentApplicationService._planning_request_with_attachments(
        "Сверь документы с шаблоном",
        [str(path)],
    )

    assert merged.startswith("Сверь документы с шаблоном")
    assert "template.csv" in merged
    assert "col1,col2" in merged
