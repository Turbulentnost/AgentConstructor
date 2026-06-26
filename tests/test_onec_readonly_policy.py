"""Тесты read-only политики 1С."""

import subprocess
import sys

import pytest

from agent_desktop_constructor.workers.models import WorkerTask
from agent_desktop_constructor.workers.onec_actions import (
    ensure_onec_readonly_input,
    ensure_onec_readonly_tool,
)
from agent_desktop_constructor.workers.onec_com_actions import execute_onec_com_readonly
from agent_desktop_constructor.workers.onec_errors import OneCReadOnlyPolicyError


@pytest.mark.parametrize(
    "tool_name",
    [
        "onec.search_documents",
        "onec.get_document_card",
        "onec.search_tasks",
        "onec.get_task_card",
    ],
)
def test_allowed_onec_tools(tool_name: str) -> None:
    """Разрешённые 1С tools проходят policy."""
    ensure_onec_readonly_tool(tool_name)


@pytest.mark.parametrize(
    "tool_name",
    [
        "onec.create_document",
        "onec.update_document",
        "onec.execute_code",
        "outlook.search_mail",
    ],
)
def test_forbidden_tool_names_raise_policy_error(tool_name: str) -> None:
    """Запрещённые tool_name блокируются."""
    with pytest.raises(OneCReadOnlyPolicyError):
        ensure_onec_readonly_tool(tool_name)


@pytest.mark.parametrize(
    "key",
    [
        "write",
        "save",
        "post",
        "delete",
        "conduct",
        "update",
        "create",
        "set_status",
        "execute_code",
        "script",
        "command",
    ],
)
def test_forbidden_input_keys_raise_policy_error(key: str) -> None:
    """write-like ключи запрещены даже во вложенных данных."""
    with pytest.raises(OneCReadOnlyPolicyError):
        ensure_onec_readonly_input({"filters": [{key: True}]})


def test_onec_create_document_is_forbidden() -> None:
    """tool_name onec.create_document запрещён."""
    with pytest.raises(OneCReadOnlyPolicyError):
        ensure_onec_readonly_tool("onec.create_document")


def test_com_stub_does_not_require_windows_or_pywin32() -> None:
    """COM stub не требует реальной 1С, Windows или pywin32."""
    task = WorkerTask(
        task_id="task-1",
        tool_name="onec.search_documents",
        input_data={"query": "x"},
    )

    result = execute_onec_com_readonly(task)

    if sys.platform != "win32":
        assert result.ok is False
        assert result.error_type == "COM_NOT_AVAILABLE"
    else:
        assert result.ok is False
        assert result.error_type in {"COM_NOT_AVAILABLE", "ONEC_CONNECTION_ERROR"}


def test_pywin32_is_not_imported_by_common_modules() -> None:
    """pywin32 не импортируется в общих 1С модулях."""
    code = (
        "import sys;"
        "import agent_desktop_constructor.tools.onec_tools;"
        "import agent_desktop_constructor.workers.onec_actions;"
        "import agent_desktop_constructor.workers.onec_worker;"
        "blocked={'win32com','win32com.client','pythoncom'};"
        "raise SystemExit(1 if blocked & set(sys.modules) else 0)"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0

