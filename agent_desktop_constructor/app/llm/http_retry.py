"""Повтор HTTP-запросов LLM при транзиентных сетевых/SSL сбоях.

HTTPError (ответ сервера с кодом) НЕ повторяется — его обрабатывает вызывающий
клиент (например, fallback без response_format при 400). Повторяются только
ошибки уровня соединения: обрыв TLS, таймаут, DNS, сброс соединения.
"""

from __future__ import annotations

import time
from typing import Callable
from urllib import error

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0


def read_with_retry(
    urlopen_callable: Callable,
    http_request,
    timeout: float,
    *,
    attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> bytes:
    """Выполнить urlopen с повтором при транзиентных сетевых ошибках.

    ``urlopen_callable`` передаётся снаружи, чтобы monkeypatch клиента
    (``client.request.urlopen``) продолжал работать в тестах.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with urlopen_callable(http_request, timeout=timeout) as response:
                return response.read()
        except error.HTTPError:
            # Ответ сервера с HTTP-кодом — не транзиентная сетевая ошибка.
            raise
        except (error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            time.sleep(backoff_seconds * attempt)
    # Недостижимо: цикл либо возвращает bytes, либо пробрасывает исключение.
    raise last_exc if last_exc is not None else RuntimeError("retry failed")
