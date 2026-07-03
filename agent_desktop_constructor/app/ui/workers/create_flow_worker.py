"""Фоновый worker для операций экрана создания агента.

Выполняет длительные вызовы ``agent_service`` (построение плана, пробный запуск,
«собрать-проверить-запустить») вне UI-потока и транслирует живой прогресс, чтобы
окно не зависало и было видно, что процесс идёт.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


class CreateFlowWorker(QObject):
    """QObject-worker: запускает переданную job и шлёт прогресс сигналами."""

    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, job: Callable[[Callable[[str], None]], object]) -> None:
        """Создать worker для job, принимающей колбэк прогресса."""
        super().__init__()
        self._job = job

    @Slot()
    def run(self) -> None:
        """Выполнить job, отправив результат/ошибку и живые строки прогресса."""
        try:
            result = self._job(self._emit_progress)
            self.completed.emit(result)
        except Exception as exc:  # noqa: BLE001 — любой сбой job показываем в UI
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def _emit_progress(self, message: str) -> None:
        """Отправить строку прогресса в UI-поток (Qt ставит сигнал в очередь)."""
        self.progress.emit(str(message))
