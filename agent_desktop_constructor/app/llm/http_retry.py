"""Повтор HTTP-запросов LLM при транзиентных сетевых/SSL сбоях.

HTTPError (ответ сервера с кодом) НЕ повторяется — его обрабатывает вызывающий
клиент (например, fallback без response_format при 400). Повторяются только
ошибки уровня соединения: обрыв TLS, таймаут, DNS, сброс соединения.

При переданном ``cancel_callback`` запрос можно прервать, не дожидаясь
полного timeout_seconds: колбэк опрашивается в фоне, а открытый response
закрывается, чтобы разблокировать ``read()``.
"""

from __future__ import annotations

import threading
import time
from typing import Callable
from urllib import error

from agent_desktop_constructor.app.llm.errors import LLMCancelledError

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_CANCEL_POLL_SECONDS = 0.25


def read_with_retry(
    urlopen_callable: Callable,
    http_request,
    timeout: float,
    *,
    attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    cancel_callback: Callable[[], bool] | None = None,
    cancel_poll_seconds: float = DEFAULT_CANCEL_POLL_SECONDS,
) -> bytes:
    """Выполнить urlopen с повтором при транзиентных сетевых ошибках.

    ``urlopen_callable`` передаётся снаружи, чтобы monkeypatch клиента
    (``client.request.urlopen``) продолжал работать в тестах.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        _raise_if_cancelled(cancel_callback)
        try:
            return _urlopen_cancellable(
                urlopen_callable,
                http_request,
                timeout,
                cancel_callback=cancel_callback,
                cancel_poll_seconds=cancel_poll_seconds,
            )
        except LLMCancelledError:
            raise
        except error.HTTPError:
            # Ответ сервера с HTTP-кодом — не транзиентная сетевая ошибка.
            raise
        except (error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            _sleep_with_cancel(
                backoff_seconds * attempt,
                cancel_callback=cancel_callback,
                cancel_poll_seconds=cancel_poll_seconds,
            )
    # Недостижимо: цикл либо возвращает bytes, либо пробрасывает исключение.
    raise last_exc if last_exc is not None else RuntimeError("retry failed")


def _raise_if_cancelled(cancel_callback: Callable[[], bool] | None) -> None:
    """Прервать запрос, если пользователь запросил остановку."""
    if cancel_callback is None:
        return
    try:
        requested = bool(cancel_callback())
    except Exception:
        return
    if requested:
        raise LLMCancelledError("Запрос к LLM отменён пользователем")


def _sleep_with_cancel(
    seconds: float,
    *,
    cancel_callback: Callable[[], bool] | None,
    cancel_poll_seconds: float,
) -> None:
    """Спать с опросом отмены (между retry-попытками)."""
    if seconds <= 0:
        _raise_if_cancelled(cancel_callback)
        return
    if cancel_callback is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        _raise_if_cancelled(cancel_callback)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(cancel_poll_seconds, remaining))


def _urlopen_cancellable(
    urlopen_callable: Callable,
    http_request,
    timeout: float,
    *,
    cancel_callback: Callable[[], bool] | None,
    cancel_poll_seconds: float,
) -> bytes:
    """Выполнить urlopen так, чтобы cancel мог прервать ожидание ответа."""
    if cancel_callback is None:
        with urlopen_callable(http_request, timeout=timeout) as response:
            return response.read()

    holder: dict = {"response": None, "data": None, "error": None}
    done = threading.Event()

    def worker() -> None:
        try:
            response = urlopen_callable(http_request, timeout=timeout)
            holder["response"] = response
            try:
                holder["data"] = response.read()
            finally:
                try:
                    response.close()
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 — передаём в вызывающий поток
            holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while not done.wait(cancel_poll_seconds):
        try:
            if cancel_callback():
                response = holder["response"]
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                raise LLMCancelledError("Запрос к LLM отменён пользователем")
        except LLMCancelledError:
            raise
        except Exception:
            # Ошибка cancel_callback не должна ронять HTTP-поток.
            pass

    if holder["error"] is not None:
        raise holder["error"]
    data = holder["data"]
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError("LLM HTTP worker завершился без данных")
    return bytes(data)
