"""Тесты прерывания HTTP-запросов LLM по cancel_callback."""

from __future__ import annotations

import threading
import time
from urllib.error import URLError

import pytest

from agent_desktop_constructor.app.llm.errors import LLMCancelledError
from agent_desktop_constructor.app.llm.http_retry import read_with_retry


class FakeHTTPResponse:
    """Минимальный response с блокирующим read()."""

    def __init__(self, payload: bytes, *, read_delay: float = 0.0) -> None:
        self._payload = payload
        self._read_delay = read_delay
        self.closed = False

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def read(self) -> bytes:
        if self._read_delay > 0:
            time.sleep(self._read_delay)
        if self.closed:
            raise OSError("response closed")
        return self._payload

    def close(self) -> None:
        self.closed = True


def test_read_with_retry_cancels_before_request() -> None:
    """Если cancel уже True до urlopen, запрос не стартует."""
    calls = {"n": 0}

    def fake_urlopen(http_request, timeout):
        calls["n"] += 1
        return FakeHTTPResponse(b'{"ok":true}')

    with pytest.raises(LLMCancelledError):
        read_with_retry(
            fake_urlopen,
            object(),
            timeout=5,
            cancel_callback=lambda: True,
        )

    assert calls["n"] == 0


def test_read_with_retry_cancels_during_slow_read() -> None:
    """Cancel во время долгого read() прерывает ожидание без полного timeout."""
    cancel = {"flag": False}
    started = threading.Event()

    def fake_urlopen(http_request, timeout):
        started.set()
        return FakeHTTPResponse(b'{"ok":true}', read_delay=2.0)

    def cancel_soon() -> bool:
        return cancel["flag"]

    def arm_cancel() -> None:
        assert started.wait(1.0)
        time.sleep(0.15)
        cancel["flag"] = True

    armer = threading.Thread(target=arm_cancel, daemon=True)
    armer.start()
    t0 = time.monotonic()
    with pytest.raises(LLMCancelledError):
        read_with_retry(
            fake_urlopen,
            object(),
            timeout=30,
            cancel_callback=cancel_soon,
            cancel_poll_seconds=0.05,
            attempts=1,
        )
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5


def test_read_with_retry_without_cancel_still_works() -> None:
    """Без cancel_callback поведение как раньше: один успешный read."""

    def fake_urlopen(http_request, timeout):
        return FakeHTTPResponse(b'{"ok":true}')

    data = read_with_retry(fake_urlopen, object(), timeout=5)
    assert data == b'{"ok":true}'


def test_read_with_retry_does_not_retry_after_cancel() -> None:
    """Отмена не должна запускать backoff/retry."""
    calls = {"n": 0}

    def fake_urlopen(http_request, timeout):
        calls["n"] += 1
        raise URLError("connection refused")

    cancel_after = {"n": 0}

    def cancel_callback() -> bool:
        cancel_after["n"] += 1
        # Уже True на первой проверке до urlopen — запрос не стартует.
        return True

    with pytest.raises(LLMCancelledError):
        read_with_retry(
            fake_urlopen,
            object(),
            timeout=5,
            attempts=3,
            cancel_callback=cancel_callback,
        )
    assert calls["n"] == 0
