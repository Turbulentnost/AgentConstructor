"""Тесты инструментов написания и запуска Python-кода в workspace агента."""

from __future__ import annotations

from pathlib import Path

from agent_desktop_constructor.tools.agent_workspace import AgentWorkspaceResolver
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.code_execution_tools import (
    CODE_SUBDIR,
    CodeRunPythonTool,
    CodeWritePythonTool,
    register_code_execution_tools,
)
from agent_desktop_constructor.tools.registry import ToolRegistry


def _ctx(agent_id: str = "agent-1", **extra) -> dict:
    """Собрать input_data с runtime_context.agent_id."""
    return {"runtime_context": {"agent_id": agent_id}, **extra}


def test_write_python_creates_file_in_code_subdir(tmp_path: Path) -> None:
    """Код сохраняется в подпапку code рабочей папки агента."""
    tool = CodeWritePythonTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(code="print('hi')", filename="hello.py"))

    assert result.ok is True
    assert result.output_data["path"] == f"{CODE_SUBDIR}/hello.py"
    saved = tmp_path / "agent-1" / CODE_SUBDIR / "hello.py"
    assert saved.read_text(encoding="utf-8") == "print('hi')"


def test_write_python_rejects_non_py_extension(tmp_path: Path) -> None:
    """Разрешены только .py файлы."""
    tool = CodeWritePythonTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(code="print(1)", filename="data.txt"))

    assert result.ok is False
    assert result.error_type == "WORKSPACE_ERROR"


def test_write_python_blocks_path_traversal(tmp_path: Path) -> None:
    """Путь скрипта не может выйти за пределы папки code."""
    tool = CodeWritePythonTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(code="print(1)", filename="../evil.py"))

    assert result.ok is False
    assert result.error_type == "WORKSPACE_ERROR"


def test_run_python_executes_and_returns_stdout(tmp_path: Path) -> None:
    """Инструмент запускает код и возвращает stdout/exit_code."""
    tool = CodeRunPythonTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(code="print('result:', 2 + 2)", filename="calc.py"))

    assert result.ok is True
    assert result.output_data["exit_code"] == 0
    assert "result: 4" in result.output_data["stdout"]
    assert result.output_data["script"] == f"{CODE_SUBDIR}/calc.py"


def test_run_python_runs_in_workspace_cwd(tmp_path: Path) -> None:
    """cwd скрипта — папка агента: он читает выгруженные файлы."""
    resolver = AgentWorkspaceResolver(tmp_path)
    workspace = resolver.for_agent("agent-1")
    (workspace.directory / "data.txt").write_text("payload-42", encoding="utf-8")
    tool = CodeRunPythonTool(resolver)

    code = "print(open('data.txt', encoding='utf-8').read())"
    result = tool.execute(_ctx(code=code, filename="reader.py"))

    assert result.ok is True
    assert "payload-42" in result.output_data["stdout"]


def test_run_python_reports_failure_with_stderr(tmp_path: Path) -> None:
    """Ошибка скрипта возвращается как неуспех с stderr для анализа LLM."""
    tool = CodeRunPythonTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(code="raise ValueError('boom')", filename="bad.py"))

    assert result.ok is False
    assert result.error_type == "SCRIPT_FAILED"
    assert "boom" in result.output_data["stderr"]


def test_run_python_requires_human_approval_in_catalog() -> None:
    """code.run_python помечен как требующий подтверждения человека."""
    catalog = load_tools_catalog()
    tool = catalog.get_tool("code.run_python")

    assert tool.requires_human_approval is True


def test_register_code_execution_tools(tmp_path: Path) -> None:
    """register_code_execution_tools добавляет оба инструмента."""
    registry = ToolRegistry()
    register_code_execution_tools(registry, AgentWorkspaceResolver(tmp_path))

    assert registry.has_tool("code.write_python")
    assert registry.has_tool("code.run_python")
