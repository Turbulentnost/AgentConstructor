"""Тесты PowerShell-инструмента в workspace агента."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_desktop_constructor.app.llm.agent_loop_prompts import build_agent_loop_prompt
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.runtime_state import (
    AgentRunStatus,
    AgentRuntimeState,
)
from agent_desktop_constructor.tools.agent_workspace import AgentWorkspaceResolver
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.powershell_tools import (
    WorkspacePowerShellRunTool,
    is_destructive_powershell_command,
    register_powershell_tools,
)
from agent_desktop_constructor.tools.registry import ToolRegistry


def _ctx(agent_id: str = "agent-1", **extra) -> dict:
    """Собрать input_data с runtime_context.agent_id."""
    return {"runtime_context": {"agent_id": agent_id}, **extra}


def test_powershell_stdout_and_workspace_cwd(tmp_path: Path, monkeypatch) -> None:
    """Команда запускается с cwd внутри workspace и возвращает stdout."""
    tool = WorkspacePowerShellRunTool(AgentWorkspaceResolver(tmp_path))
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(args, 0, stdout="hello\n", stderr="")

    monkeypatch.setattr(tool, "_find_powershell", lambda: "powershell")
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.powershell_tools.subprocess.run",
        fake_run,
    )

    result = tool.execute(_ctx(command="Write-Output hello"))

    expected_cwd = tmp_path / "agent-1"
    assert result.ok is True
    assert result.output_data["stdout"] == "hello\n"
    assert result.output_data["cwd"] == str(expected_cwd.resolve())
    assert captured["cwd"] == str(expected_cwd.resolve())


def test_powershell_working_subdir_stays_inside_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """working_subdir резолвится только внутри workspace агента."""
    tool = WorkspacePowerShellRunTool(AgentWorkspaceResolver(tmp_path))
    workspace = AgentWorkspaceResolver(tmp_path).for_agent("agent-1")
    subdir = workspace.directory / "docs"
    subdir.mkdir()
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(tool, "_find_powershell", lambda: "powershell")
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.powershell_tools.subprocess.run",
        fake_run,
    )

    result = tool.execute(_ctx(command="Get-ChildItem", working_subdir="docs"))

    assert result.ok is True
    assert captured["cwd"] == str(subdir.resolve())


def test_powershell_working_subdir_cannot_escape_workspace(tmp_path: Path) -> None:
    """working_subdir с path traversal блокируется."""
    tool = WorkspacePowerShellRunTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(command="Get-ChildItem", working_subdir=".."))

    assert result.ok is False
    assert result.error_type == "WORKSPACE_ERROR"


def test_destructive_command_without_approval_is_blocked(tmp_path: Path) -> None:
    """Remove-Item/rm/del и похожие команды требуют подтверждения человека."""
    tool = WorkspacePowerShellRunTool(AgentWorkspaceResolver(tmp_path))

    result = tool.execute(_ctx(command="Remove-Item report.txt"))

    assert result.ok is False
    assert result.error_type == "HUMAN_APPROVAL_REQUIRED"
    assert result.requires_human_approval is True


def test_destructive_command_with_approval_executes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """После explicit approval destructive-команда передаётся subprocess."""
    tool = WorkspacePowerShellRunTool(AgentWorkspaceResolver(tmp_path))
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="approved\n", stderr="")

    monkeypatch.setattr(tool, "_find_powershell", lambda: "powershell")
    monkeypatch.setattr(
        "agent_desktop_constructor.tools.powershell_tools.subprocess.run",
        fake_run,
    )

    result = tool.execute(_ctx(command="Remove-Item report.txt", human_approved=True))

    assert result.ok is True
    assert result.output_data["stdout"] == "approved\n"
    assert calls


def test_destructive_classifier_covers_common_aliases() -> None:
    """Классификатор видит типичные destructive PowerShell-команды."""
    assert is_destructive_powershell_command("rm old.txt")
    assert is_destructive_powershell_command("del old.txt")
    assert is_destructive_powershell_command("Clear-Content log.txt")
    assert is_destructive_powershell_command("Set-Content report.txt ''")
    assert not is_destructive_powershell_command("Get-ChildItem")


def test_registry_registers_powershell_tool(tmp_path: Path) -> None:
    """register_powershell_tools добавляет workspace.powershell_run."""
    registry = ToolRegistry()
    register_powershell_tools(registry, AgentWorkspaceResolver(tmp_path))

    assert registry.has_tool("workspace.powershell_run")


def test_prompt_context_includes_powershell_output() -> None:
    """stdout команды попадает в collected_data и agent_context следующего prompt."""
    agent_spec = AgentBuilder().build_from_request("помоги структурировать информацию")
    state = AgentRuntimeState(
        run_id="run-1",
        agent_id=agent_spec.agent_id,
        status=AgentRunStatus.RUNNING,
        variables={
            "user_request": "посмотри файлы",
            "tool_outputs": {
                "workspace.powershell_run": {
                    "stdout": "file-a.txt\n",
                    "stdout_summary": "file-a.txt\n",
                    "stderr": "",
                }
            },
        },
    )
    state.add_tool_result(
        tool_name="workspace.powershell_run",
        input_data={"command": "Get-ChildItem"},
        output_data={
            "stdout": "file-a.txt\n",
            "stdout_summary": "file-a.txt\n",
            "stderr": "",
        },
        ok=True,
    )

    messages = build_agent_loop_prompt(
        agent_spec,
        state,
        load_tools_catalog(),
        executed_signatures=[],
        repeat_notes=[],
    )
    payload = json.loads(messages[1].content.split("\n", 1)[1])

    assert "file-a.txt" in json.dumps(payload["collected_data"], ensure_ascii=False)
    assert "file-a.txt" in json.dumps(payload["agent_context"], ensure_ascii=False)
