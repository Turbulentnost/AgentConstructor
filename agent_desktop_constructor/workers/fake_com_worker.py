"""Fake COM worker для тестов и разработки без Windows-приложений."""

from agent_desktop_constructor.workers.base import BaseWorker
from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask


class FakeComWorker(BaseWorker):
    """Fake worker, возвращающий заранее заданные ответы без COM-вызовов."""

    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        simulate_error: bool = False,
    ) -> None:
        """Создать fake worker с ответами по tool_name."""
        self._responses = responses or {}
        self._simulate_error = simulate_error

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Вернуть fake-ответ для tool_name или структурированную ошибку."""
        if self._simulate_error:
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="FAKE_WORKER_ERROR",
                error_message="Fake worker вернул тестовую ошибку",
            )

        if task.tool_name not in self._responses:
            return WorkerResult(
                task_id=task.task_id,
                ok=False,
                error_type="FAKE_RESPONSE_NOT_FOUND",
                error_message="Для инструмента не задан fake-ответ",
            )

        return WorkerResult(
            task_id=task.task_id,
            ok=True,
            output_data=self._responses[task.tool_name],
        )
