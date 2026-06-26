"""Тесты OneCReadOnlyWorker без реальной 1С."""

from agent_desktop_constructor.workers.models import WorkerTask
from agent_desktop_constructor.workers.onec_worker import OneCReadOnlyWorker


def make_task(tool_name: str, input_data: dict | None = None) -> WorkerTask:
    """Создать WorkerTask для 1С."""
    return WorkerTask(
        task_id="task-1",
        tool_name=tool_name,
        input_data=input_data or {},
    )


def test_worker_search_documents() -> None:
    """OneCReadOnlyWorker выполняет onec.search_documents."""
    result = OneCReadOnlyWorker().execute(make_task("onec.search_documents"))

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["documents"][0]["ref"] == "doc-ref-1"


def test_worker_get_document_card() -> None:
    """OneCReadOnlyWorker выполняет onec.get_document_card."""
    result = OneCReadOnlyWorker().execute(
        make_task("onec.get_document_card", {"document_ref": "doc-ref-1"})
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["document"]["ref"] == "doc-ref-1"


def test_worker_search_tasks() -> None:
    """OneCReadOnlyWorker выполняет onec.search_tasks."""
    result = OneCReadOnlyWorker().execute(make_task("onec.search_tasks"))

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["tasks"][0]["ref"] == "task-ref-1"


def test_worker_get_task_card() -> None:
    """OneCReadOnlyWorker выполняет onec.get_task_card."""
    result = OneCReadOnlyWorker().execute(
        make_task("onec.get_task_card", {"task_ref": "task-ref-1"})
    )

    assert result.ok is True
    assert result.output_data is not None
    assert result.output_data["task"]["ref"] == "task-ref-1"


def test_unknown_tool_is_forbidden() -> None:
    """unknown tool запрещён."""
    result = OneCReadOnlyWorker().execute(make_task("onec.unknown"))

    assert result.ok is False
    assert result.error_type == "ONEC_READONLY_POLICY_ERROR"


def test_write_keys_are_forbidden() -> None:
    """write ключи в input_data запрещены."""
    result = OneCReadOnlyWorker().execute(
        make_task("onec.search_documents", {"query": "x", "write": True})
    )

    assert result.ok is False
    assert result.error_type == "ONEC_READONLY_POLICY_ERROR"


def test_execute_code_script_command_are_forbidden() -> None:
    """execute_code/script/command запрещены."""
    worker = OneCReadOnlyWorker()
    for key in ["execute_code", "script", "command"]:
        result = worker.execute(make_task("onec.search_tasks", {key: "bad"}))
        assert result.ok is False
        assert result.error_type == "ONEC_READONLY_POLICY_ERROR"

