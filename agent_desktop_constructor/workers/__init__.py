"""External integration worker package."""

from agent_desktop_constructor.workers.base import BaseWorker
from agent_desktop_constructor.workers.com_availability import (
    get_com_unavailable_reason,
    is_pywin32_available,
    is_windows,
)
from agent_desktop_constructor.workers.fake_com_worker import FakeComWorker
from agent_desktop_constructor.workers.models import WorkerResult, WorkerTask

__all__ = [
    "BaseWorker",
    "FakeComWorker",
    "WorkerResult",
    "WorkerTask",
    "get_com_unavailable_reason",
    "is_pywin32_available",
    "is_windows",
]
