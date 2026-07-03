"""Unit-тесты BrowserVisionWorker без запуска реального браузера."""

from __future__ import annotations

import pytest

from agent_desktop_constructor.workers.browser_cdp_worker import BrowserCdpError
from agent_desktop_constructor.workers.browser_vision_worker import (
    BrowserVisionWorker,
)


class FakeVisionSession:
    """Fake CDP session, записывающая отправленные команды."""

    def __init__(self, scroll_metrics: dict | None = None) -> None:
        self.sent: list[tuple[str, dict | None]] = []
        self.evaluated: list[str] = []
        self._scroll_metrics = scroll_metrics or {
            "scrolled": True,
            "scroll_top": 700,
            "scroll_height": 5000,
            "client_height": 900,
            "at_bottom": False,
            "at_top": False,
            "target": "div.chat-list",
        }

    def __enter__(self) -> "FakeVisionSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def send(self, method: str, params: dict | None = None) -> dict:
        self.sent.append((method, params))
        if method == "Page.captureScreenshot":
            return {"data": "SCREENSHOTB64"}
        return {}

    def evaluate(self, expression: str):
        self.evaluated.append(expression)
        if "scrollableAxis" in expression:
            return dict(self._scroll_metrics)
        if "location.href" in expression:
            return "https://example.com/app"
        if "document.title" in expression:
            return "App"
        if "innerWidth" in expression:
            return {"w": 1280, "h": 900}
        if "document.readyState" in expression:
            return "complete"
        return None


def _worker_with_fake(monkeypatch: pytest.MonkeyPatch) -> tuple[BrowserVisionWorker, FakeVisionSession]:
    worker = BrowserVisionWorker()
    session = FakeVisionSession()
    monkeypatch.setattr(worker, "_session", lambda: session)
    return worker, session


def test_screenshot_returns_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    """screenshot возвращает base64 PNG и состояние страницы."""
    worker, _ = _worker_with_fake(monkeypatch)

    result = worker.screenshot({})

    assert result["screenshot_base64"] == "SCREENSHOTB64"
    assert result["screenshot_media_type"] == "image/png"
    assert result["url"] == "https://example.com/app"
    assert result["viewport_width"] == 1280


def test_click_dispatches_mouse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """click отправляет mousePressed/mouseReleased по координатам и делает скриншот."""
    worker, session = _worker_with_fake(monkeypatch)

    result = worker.click({"x": 100, "y": 200})

    mouse_events = [p for m, p in session.sent if m == "Input.dispatchMouseEvent"]
    assert {e["type"] for e in mouse_events} == {"mousePressed", "mouseReleased"}
    assert mouse_events[0]["x"] == 100 and mouse_events[0]["y"] == 200
    assert result["screenshot_base64"] == "SCREENSHOTB64"


def test_type_text_uses_insert_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """type_text отправляет Input.insertText с текстом."""
    worker, session = _worker_with_fake(monkeypatch)

    worker.type_text({"text": "привет"})

    inserts = [p for m, p in session.sent if m == "Input.insertText"]
    assert inserts and inserts[0]["text"] == "привет"


def test_type_text_requires_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой text приводит к понятной ошибке."""
    worker, _ = _worker_with_fake(monkeypatch)

    with pytest.raises(BrowserCdpError):
        worker.type_text({"text": ""})


def test_press_key_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    """press_key enter отправляет key-события с кодом 13."""
    worker, session = _worker_with_fake(monkeypatch)

    worker.press_key({"key": "enter"})

    key_events = [p for m, p in session.sent if m == "Input.dispatchKeyEvent"]
    assert key_events and key_events[0]["windowsVirtualKeyCode"] == 13


def test_press_key_unknown_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неизвестная клавиша отвергается."""
    worker, _ = _worker_with_fake(monkeypatch)

    with pytest.raises(BrowserCdpError):
        worker.press_key({"key": "f13"})


def test_scroll_targets_container_and_reports_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """scroll ищет прокручиваемую область и возвращает метрики прокрутки."""
    worker, session = _worker_with_fake(monkeypatch)

    result = worker.scroll({"direction": "down", "pixels": 500})

    assert result["screenshot_base64"] == "SCREENSHOTB64"
    assert result["scrolled"] is True
    assert result["at_bottom"] is False
    assert result["scroll_target"] == "div.chat-list"
    # Использован скрипт поиска прокручиваемого контейнера, а не тупой window.scrollBy.
    assert any("scrollableAxis" in expr for expr in session.evaluated)


def test_scroll_reports_no_move_at_bottom(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если область не сдвинулась, scroll честно сообщает scrolled=false/at_bottom."""
    worker = BrowserVisionWorker()
    session = FakeVisionSession(
        scroll_metrics={
            "scrolled": False,
            "scroll_top": 4100,
            "scroll_height": 5000,
            "client_height": 900,
            "at_bottom": True,
            "at_top": False,
            "target": "div.chat-list",
        }
    )
    monkeypatch.setattr(worker, "_session", lambda: session)

    result = worker.scroll({"direction": "down", "pixels": 500})

    assert result["scrolled"] is False
    assert result["at_bottom"] is True


def test_click_requires_numeric_coords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нечисловые координаты дают понятную ошибку."""
    worker, _ = _worker_with_fake(monkeypatch)

    with pytest.raises(BrowserCdpError):
        worker.click({"x": "left", "y": 10})
